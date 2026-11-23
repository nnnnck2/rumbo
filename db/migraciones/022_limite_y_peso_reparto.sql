-- 022 · SCRUM-54 (RF-15) · Límite de leads pendientes y peso de reparto por asesor
--   · asesor.max_pendientes: cuántos leads "por llamar ahora" puede tener a la vez (NULL = sin límite).
--     Pendiente = lead asignado a él cuya llamada ya toca (nuevo sin gestionar, reintento o agenda vencida).
--     Las llamadas agendadas para más adelante no cuentan: no es carga de este momento.
--     Un asesor en el límite se salta en el reparto. Si TODOS están en el límite, el lead queda en cola y
--     liberar_cola() (cada 5 min) lo reparte en cuanto alguien baje del límite: el cliente no se pierde.
--   · asesor.peso_reparto (0.10 a 1.00, 1 por defecto): con 0.5 recibe la mitad de leads que los demás
--     (p. ej. asesores nuevos). Reparto ponderado por "pases" (stride scheduling): cada asesor tiene un pase;
--     se elige al de pase más bajo y, al recibir un lead, su pase sube 1/peso. Con todos en peso 1 es el mismo
--     round robin de antes. Quien entra al turno tarde arranca en el pase más bajo del equipo, así no recibe
--     una ráfaga de leads para "ponerse al día".
--   · La reasignación manual del supervisor (reasignar_manual) no mira el límite: es su decisión.

ALTER TABLE rumbo.asesor
    ADD COLUMN max_pendientes smallint CHECK (max_pendientes BETWEEN 1 AND 200),
    ADD COLUMN peso_reparto   numeric(3,2) NOT NULL DEFAULT 1 CHECK (peso_reparto BETWEEN 0.10 AND 1.00),
    ADD COLUMN reparto_pase   numeric(14,4) NOT NULL DEFAULT 0 CHECK (reparto_pase >= 0);
COMMENT ON COLUMN rumbo.asesor.max_pendientes IS 'SCRUM-54: máximo de leads por llamar ahora; NULL = sin límite.';
COMMENT ON COLUMN rumbo.asesor.peso_reparto IS 'SCRUM-54: parte de leads que recibe frente a un asesor de peso 1.';
COMMENT ON COLUMN rumbo.asesor.reparto_pase IS 'SCRUM-54: pase del reparto ponderado (lo maneja _repartir).';

-- El pase cambia en cada reparto: que no llene la auditoría (igual que ultimo_lead_en).
DROP TRIGGER auditar ON rumbo.asesor;
CREATE TRIGGER auditar AFTER INSERT OR UPDATE OR DELETE ON rumbo.asesor
    FOR EACH ROW EXECUTE FUNCTION auditoria.tg_registrar('ultimo_lead_en,estado_desde,reparto_pase', '');

-- Leads que ya le toca llamar a un asesor (sin contar p_excepto, el que se está repartiendo).
CREATE FUNCTION rumbo.pendientes_asesor(p_asesor_id bigint, p_excepto bigint DEFAULT NULL) RETURNS integer
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
    SELECT count(*)::integer FROM rumbo.lead l
    WHERE l.asesor_id = p_asesor_id AND l.estado_asignacion = 'asignado'
      AND (l.proxima_accion_en IS NULL OR l.proxima_accion_en <= now())
      AND l.id IS DISTINCT FROM p_excepto
$$;

-- Igual que 019 (vueltas + especialidad), con el límite de pendientes y el reparto ponderado.
CREATE OR REPLACE FUNCTION rumbo._repartir(p_lead_id bigint, p_motivo rumbo.motivo_asignacion, p_excluir bigint DEFAULT NULL)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_lead   rumbo.lead;
    v_asesor bigint;
    v_vuelta smallint;
    v_ya     bigint[];
    v_libres bigint[];          -- en turno y por debajo de su límite de pendientes
    v_pase   numeric;           -- pase más bajo entre los libres
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
        SELECT coalesce(array_agg(a.id), '{}'), min(a.reparto_pase) INTO v_libres, v_pase
        FROM rumbo.asesor a
        JOIN rumbo.usuario u ON u.id = a.usuario_id
        WHERE u.activo AND a.estado IN ('disponible', 'ocupado')
          AND (a.max_pendientes IS NULL OR rumbo.pendientes_asesor(a.id, p_lead_id) < a.max_pendientes);

        -- 1) alguien libre que aún no lo tuvo en esta vuelta: disponible antes que ocupado, especialista,
        --    pase más bajo (round robin ponderado) y, a igual pase, el que hace más que no recibe.
        SELECT a.id INTO v_asesor
        FROM rumbo.asesor a
        WHERE a.id = ANY (v_libres)
          AND a.id <> ALL (v_ya)
          AND a.id IS DISTINCT FROM p_excluir
        ORDER BY (a.estado <> 'disponible'),
                 NOT rumbo._es_especialista(a.preferencias, v_lead.tipo_visa, v_lead.pais_interes),
                 greatest(a.reparto_pase, v_pase),
                 a.ultimo_lead_en NULLS FIRST, a.id
        LIMIT 1
        FOR UPDATE OF a;

        -- 2) ya pasó por todos los libres: vuelta nueva desde el primero de la vuelta anterior
        IF v_asesor IS NULL AND cardinality(v_ya) > 0 THEN
            SELECT a.id INTO v_asesor
            FROM rumbo.asesor a
            LEFT JOIN LATERAL (SELECT min(s.creado_en) AS desde FROM rumbo.asignacion s
                               WHERE s.lead_id = p_lead_id AND s.vuelta = v_vuelta AND s.asesor_id = a.id) o ON true
            WHERE a.id = ANY (v_libres)
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
    UPDATE rumbo.asesor
    SET ultimo_lead_en = clock_timestamp(),
        reparto_pase = greatest(reparto_pase, coalesce(v_pase, 0)) + 1 / peso_reparto
    WHERE id = v_asesor;
    INSERT INTO rumbo.asignacion (lead_id, asesor_anterior_id, asesor_id, motivo, asignado_por_usuario_id, vuelta)
    VALUES (p_lead_id, v_lead.asesor_id, v_asesor, p_motivo, rumbo.ctx_usuario_id(), v_vuelta);
    RETURN v_asesor;
END $$;

-- El admin fija el límite y el peso de un asesor.
CREATE FUNCTION rumbo.guardar_carga_asesor(p_asesor_id bigint, p_max_pendientes smallint, p_peso numeric)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    PERFORM rumbo._exigir_rol('admin');
    UPDATE rumbo.asesor SET max_pendientes = p_max_pendientes, peso_reparto = coalesce(p_peso, 1)
    WHERE id = p_asesor_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'El asesor % no existe', p_asesor_id USING ERRCODE = 'no_data_found';
    END IF;
EXCEPTION WHEN check_violation THEN
    RAISE EXCEPTION 'Límite entre 1 y 200 leads y peso entre 0.10 y 1.00' USING ERRCODE = 'RB422';
END $$;

GRANT EXECUTE ON FUNCTION rumbo.guardar_carga_asesor(bigint, smallint, numeric), rumbo.pendientes_asesor(bigint, bigint)
TO rumbo_app;
