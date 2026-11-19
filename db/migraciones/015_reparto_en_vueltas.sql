-- 015 · Reparto en vueltas y plazo de gestión de 30 minutos (pedido del área, nov-2026)
--   · Si el asesor no gestiona un lead (no registra ninguna llamada) en 30 minutos de turno,
--     pasa automáticamente a otro asesor (reasignar_sin_primera_llamada, ya existente).
--   · El lead recorre a TODOS los asesores en turno, uno por uno, sin repetir. Cuando ya pasó
--     por todos, empieza una vuelta nueva desde el primer asesor de la vuelta anterior: el
--     cliente nunca se queda sin gestionar. Antes solo se excluía al asesor anterior, y el lead
--     podía ir y volver entre dos asesores sin llegar nunca al tercero.
--   · rumbo.plazos_gestion(): cuánto le queda a cada lead sin gestionar (para mostrarlo en pantalla).

-- ─────────────────────────────── Vuelta de cada asignación ───────────────────────────────

-- El DEFAULT rellena las filas existentes (vuelta 1) sin UPDATE: la tabla es de solo inserción.
ALTER TABLE rumbo.asignacion ADD COLUMN vuelta smallint NOT NULL DEFAULT 1 CHECK (vuelta >= 1);
ALTER TABLE rumbo.asignacion ALTER COLUMN vuelta DROP DEFAULT;      -- desde ahora la pone el trigger
COMMENT ON COLUMN rumbo.asignacion.vuelta IS
    'Vuelta del reparto: 1 la primera; sube cuando el lead ya pasó por todos los asesores en turno.';

-- Las asignaciones que no indican vuelta (manual, reparto inicial) quedan en la vuelta actual del lead.
CREATE FUNCTION rumbo.tg_asignacion_vuelta() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, rumbo AS $$
BEGIN
    IF NEW.vuelta IS NULL THEN
        NEW.vuelta := coalesce((SELECT max(s.vuelta) FROM rumbo.asignacion s WHERE s.lead_id = NEW.lead_id), 1);
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER asignacion_vuelta BEFORE INSERT ON rumbo.asignacion
    FOR EACH ROW EXECUTE FUNCTION rumbo.tg_asignacion_vuelta();

-- ─────────────────────────────── Reparto ───────────────────────────────

-- Asigna el lead al siguiente asesor en turno (disponible u ocupado; si todos están ocupados igual
-- se asigna, el lead no se pierde). Orden:
--   1) un asesor que todavía NO tuvo el lead en esta vuelta (ni el que se lo acaban de quitar):
--      disponible antes que ocupado y, entre ellos, el que hace más tiempo recibió un lead;
--   2) si ya pasó por todos: vuelta nueva, empezando por el primero de la vuelta anterior.
-- Fuera de horario o sin nadie en turno, el lead queda en cola.
CREATE OR REPLACE FUNCTION rumbo._repartir(p_lead_id bigint, p_motivo rumbo.motivo_asignacion, p_excluir bigint DEFAULT NULL)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_lead   rumbo.lead;
    v_asesor bigint;
    v_vuelta smallint;
    v_ya     bigint[];
BEGIN
    PERFORM rumbo._bloquear_reparto();

    SELECT * INTO v_lead FROM rumbo.lead WHERE id = p_lead_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'El lead % no existe', p_lead_id USING ERRCODE = 'no_data_found';
    END IF;
    IF v_lead.estado_asignacion = 'cerrado' THEN
        RAISE EXCEPTION 'El lead % está cerrado', p_lead_id USING ERRCODE = 'RB422';
    END IF;

    SELECT coalesce(max(s.vuelta), 1) INTO v_vuelta FROM rumbo.asignacion s WHERE s.lead_id = p_lead_id;
    SELECT coalesce(array_agg(DISTINCT s.asesor_id), '{}') INTO v_ya
    FROM rumbo.asignacion s WHERE s.lead_id = p_lead_id AND s.vuelta = v_vuelta;

    IF rumbo.en_horario() THEN
        -- 1) alguien en turno que aún no lo tuvo en esta vuelta
        SELECT a.id INTO v_asesor
        FROM rumbo.asesor a
        JOIN rumbo.usuario u ON u.id = a.usuario_id
        WHERE u.activo AND a.estado IN ('disponible', 'ocupado')
          AND a.id <> ALL (v_ya)
          AND a.id IS DISTINCT FROM p_excluir
        ORDER BY (a.estado <> 'disponible'), a.ultimo_lead_en NULLS FIRST, a.id
        LIMIT 1
        FOR UPDATE OF a;

        -- 2) ya pasó por todos: vuelta nueva desde el primero de la vuelta anterior
        IF v_asesor IS NULL AND cardinality(v_ya) > 0 THEN
            SELECT a.id INTO v_asesor
            FROM rumbo.asesor a
            JOIN rumbo.usuario u ON u.id = a.usuario_id
            LEFT JOIN LATERAL (SELECT min(s.creado_en) AS desde FROM rumbo.asignacion s
                               WHERE s.lead_id = p_lead_id AND s.vuelta = v_vuelta AND s.asesor_id = a.id) o ON true
            WHERE u.activo AND a.estado IN ('disponible', 'ocupado')
            ORDER BY (o.desde IS NULL), o.desde, (a.estado <> 'disponible'), a.ultimo_lead_en NULLS FIRST, a.id
            LIMIT 1
            FOR UPDATE OF a;
            IF v_asesor IS NOT NULL THEN
                v_vuelta := v_vuelta + 1;
            END IF;
        END IF;
    END IF;

    IF v_asesor IS NULL THEN
        UPDATE rumbo.lead
        SET estado_asignacion = 'en_cola', asesor_id = NULL, asignado_en = NULL,
            intentos_asesor_actual = 0, proxima_accion_en = NULL
        WHERE id = p_lead_id;
        RETURN NULL;
    END IF;

    UPDATE rumbo.lead
    SET asesor_id = v_asesor, estado_asignacion = 'asignado', asignado_en = now(),
        intentos_asesor_actual = 0, proxima_accion_en = now()
    WHERE id = p_lead_id;

    -- clock_timestamp y no now(): varios repartos en la misma transacción deben avanzar el turno.
    UPDATE rumbo.asesor SET ultimo_lead_en = clock_timestamp() WHERE id = v_asesor;

    INSERT INTO rumbo.asignacion (lead_id, asesor_anterior_id, asesor_id, motivo, asignado_por_usuario_id, vuelta)
    VALUES (p_lead_id, v_lead.asesor_id, v_asesor, p_motivo, rumbo.ctx_usuario_id(), v_vuelta);

    RETURN v_asesor;
END $$;

-- ─────────────────────────────── Plazo de gestión ───────────────────────────────

-- Leads asignados que su asesor todavía no gestionó (sin llamada registrada desde que lo recibió)
-- y cuándo vence el plazo. El plazo solo corre dentro del turno (igual que reasignar_sin_primera_llamada).
-- SECURITY INVOKER: con RLS, el asesor ve solo los suyos y el supervisor todos.
CREATE FUNCTION rumbo.plazos_gestion()
RETURNS TABLE (lead_id bigint, vence_en timestamptz, vuelta smallint)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog, rumbo AS $$
    SELECT l.id,
           greatest(l.asignado_en, rumbo.inicio_turno())
               + make_interval(mins => rumbo.config_int('minutos_primera_llamada', 30)),
           (SELECT max(s.vuelta) FROM rumbo.asignacion s WHERE s.lead_id = l.id)
    FROM rumbo.lead l
    WHERE l.estado_asignacion = 'asignado'
      AND NOT EXISTS (SELECT 1 FROM rumbo.intento_llamada i
                      WHERE i.lead_id = l.id AND i.asesor_id = l.asesor_id AND i.creado_en >= l.asignado_en)
      AND (l.proxima_accion_en IS NULL OR l.proxima_accion_en <= now())
$$;
GRANT EXECUTE ON FUNCTION rumbo.plazos_gestion() TO rumbo_app;

-- ─────────────────────────────── 30 minutos para gestionar ───────────────────────────────

-- El área definió 30 minutos (antes 15, pendiente de confirmar). Solo se cambia si nadie lo tocó.
UPDATE rumbo.configuracion
SET valor = '30',
    descripcion = 'Minutos (de turno) que tiene el asesor para gestionar un lead nuevo antes de que pase a otro asesor.'
WHERE clave = 'minutos_primera_llamada' AND valor = '15'::jsonb;
