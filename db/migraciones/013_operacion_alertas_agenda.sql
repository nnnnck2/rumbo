-- 013 · Sprint 4 (operación): SCRUM-37, SCRUM-39, SCRUM-40
--   · rumbo.inicio_turno(): hora de apertura de hoy según la configuración.
--   · RF-14 (SCRUM-39): el plazo de la primera llamada solo cuenta dentro del turno. Antes, un lead
--     asignado a las 17:55 se le quitaba al asesor a las 9:01 del día siguiente (contaba la noche).
--   · RF-24 (SCRUM-37): rumbo.agendar_llamada(), reprogramar la llamada sin registrar un intento.
--   · RF-33 (SCRUM-40): rumbo.leads_sin_llamar() y la clave de configuración minutos_alerta_supervisor.

-- ─────────────────────────────── Turno ───────────────────────────────

-- Apertura del día de p_momento (en la zona configurada). Sin horario configurado: -infinity
-- (todo el tiempo cuenta, como antes).
CREATE FUNCTION rumbo.inicio_turno(p_momento timestamptz DEFAULT now()) RETURNS timestamptz
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    c jsonb;
BEGIN
    SELECT valor INTO c FROM rumbo.configuracion WHERE clave = 'horario';
    IF c IS NULL THEN
        RETURN '-infinity';
    END IF;
    RETURN ((p_momento AT TIME ZONE (c ->> 'zona'))::date + (c ->> 'inicio')::time) AT TIME ZONE (c ->> 'zona');
END $$;

-- ─────────────────────────────── RF-14 ───────────────────────────────

CREATE OR REPLACE FUNCTION rumbo.reasignar_sin_primera_llamada()
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_minutos integer := rumbo.config_int('minutos_primera_llamada', 15);
    v_total   integer := 0;
    r         record;
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    IF NOT rumbo.en_horario() THEN
        RETURN 0;
    END IF;
    PERFORM rumbo._bloquear_reparto();

    FOR r IN
        SELECT l.id, l.asesor_id
        FROM rumbo.lead l
        WHERE l.estado_asignacion = 'asignado'
          -- Solo cuenta tiempo dentro del turno: lo asignado ayer a las 17:55 no vence a las 9:01.
          AND greatest(l.asignado_en, rumbo.inicio_turno()) < now() - make_interval(mins => v_minutos)
          AND NOT EXISTS (SELECT 1 FROM rumbo.intento_llamada i
                          WHERE i.lead_id = l.id AND i.asesor_id = l.asesor_id AND i.creado_en >= l.asignado_en)
          AND (l.proxima_accion_en IS NULL OR l.proxima_accion_en <= now())
        ORDER BY l.id
        FOR UPDATE OF l SKIP LOCKED
    LOOP
        PERFORM rumbo._repartir(r.id, 'sin_primera_llamada', r.asesor_id);
        v_total := v_total + 1;
    END LOOP;
    RETURN v_total;
END $$;

-- ─────────────────────────────── RF-24 · Agendar ───────────────────────────────

-- Reprograma la próxima llamada sin registrar un intento (p. ej. el cliente pidió por WhatsApp
-- que lo llamen mañana). Para agendar tras hablar con el cliente se usa el resultado
-- "llamar después" de registrar_intento.
CREATE FUNCTION rumbo.agendar_llamada(p_lead_id bigint, p_version integer, p_cuando timestamptz)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_rol  rumbo.rol_usuario;
    v_lead rumbo.lead;
BEGIN
    v_rol := rumbo._exigir_rol('asesor', 'supervisor', 'admin');
    PERFORM rumbo._bloquear_reparto();
    v_lead := rumbo._tomar_lead(p_lead_id, p_version, v_rol);

    IF v_lead.estado_asignacion <> 'asignado' THEN
        RAISE EXCEPTION 'El lead % no está asignado (estado %)', p_lead_id, v_lead.estado_asignacion USING ERRCODE = 'RB422';
    END IF;
    IF p_cuando IS NULL OR p_cuando <= now() THEN
        RAISE EXCEPTION 'La llamada se debe agendar en una fecha futura' USING ERRCODE = 'RB422';
    END IF;
    IF p_cuando > now() + interval '90 days' THEN
        RAISE EXCEPTION 'No se puede agendar a más de 90 días' USING ERRCODE = 'RB422';
    END IF;

    UPDATE rumbo.lead SET proxima_accion_en = p_cuando WHERE id = p_lead_id;
    RETURN (SELECT l.version FROM rumbo.lead l WHERE l.id = p_lead_id);
END $$;

-- ─────────────────────────────── RF-33 · Alerta de leads sin llamar ───────────────────────────────

CREATE OR REPLACE FUNCTION rumbo.tg_validar_configuracion() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v jsonb := NEW.valor;
    d jsonb;
BEGIN
    CASE NEW.clave
    WHEN 'horario' THEN
        IF jsonb_typeof(v) <> 'object' OR NOT v ?& ARRAY['inicio', 'fin', 'dias', 'zona'] THEN
            RAISE EXCEPTION 'horario requiere {inicio, fin, dias, zona}';
        END IF;
        IF (v ->> 'inicio')::time >= (v ->> 'fin')::time THEN
            RAISE EXCEPTION 'horario: inicio debe ser menor que fin';
        END IF;
        PERFORM now() AT TIME ZONE (v ->> 'zona');                    -- zona horaria válida
        IF jsonb_typeof(v -> 'dias') <> 'array' OR jsonb_array_length(v -> 'dias') = 0 THEN
            RAISE EXCEPTION 'horario.dias debe ser una lista de días ISO (1 = lunes … 7 = domingo)';
        END IF;
        FOR d IN SELECT * FROM jsonb_array_elements(v -> 'dias') LOOP
            IF jsonb_typeof(d) <> 'number' OR d::int NOT BETWEEN 1 AND 7 THEN
                RAISE EXCEPTION 'horario.dias contiene un día inválido: %', d;
            END IF;
        END LOOP;
    WHEN 'max_intentos_por_asesor' THEN
        IF jsonb_typeof(v) <> 'number' OR v::int NOT BETWEEN 1 AND 10 THEN
            RAISE EXCEPTION 'max_intentos_por_asesor debe ser un número entre 1 y 10';
        END IF;
    WHEN 'minutos_primera_llamada' THEN
        IF jsonb_typeof(v) <> 'number' OR v::int NOT BETWEEN 1 AND 240 THEN
            RAISE EXCEPTION 'minutos_primera_llamada debe ser un número entre 1 y 240';
        END IF;
    WHEN 'minutos_entre_reintentos' THEN
        IF jsonb_typeof(v) <> 'number' OR v::int NOT BETWEEN 1 AND 1440 THEN
            RAISE EXCEPTION 'minutos_entre_reintentos debe ser un número entre 1 y 1440';
        END IF;
    WHEN 'minutos_alerta_supervisor' THEN
        IF jsonb_typeof(v) <> 'number' OR v::int NOT BETWEEN 1 AND 480 THEN
            RAISE EXCEPTION 'minutos_alerta_supervisor debe ser un número entre 1 y 480';
        END IF;
    WHEN 'texto_bienvenida', 'texto_fuera_horario', 'texto_privacidad' THEN
        IF jsonb_typeof(v) <> 'string' OR length(v #>> '{}') NOT BETWEEN 1 AND 1024 THEN
            RAISE EXCEPTION '% debe ser un texto de 1 a 1024 caracteres', NEW.clave;
        END IF;
    ELSE
        RAISE EXCEPTION 'Clave de configuración desconocida: %', NEW.clave;
    END CASE;
    RETURN NEW;
EXCEPTION
    WHEN invalid_datetime_format OR invalid_parameter_value OR invalid_text_representation
      OR datetime_field_overflow OR raise_exception THEN
        RAISE EXCEPTION 'Configuración inválida (%): %', NEW.clave, SQLERRM USING ERRCODE = 'RB422';
END $$;

INSERT INTO rumbo.configuracion (clave, valor, descripcion) VALUES
    ('minutos_alerta_supervisor', '30',
     'RF-33: minutos de atraso de una llamada pendiente antes de alertar al supervisor.')
ON CONFLICT (clave) DO NOTHING;

-- Leads cuya llamada está atrasada más de minutos_alerta_supervisor, dentro del turno:
--   · sin_primera_llamada : asignado y nadie lo llamó todavía
--   · reintento_vencido   : "no contesta" y el reintento ya debió hacerse
--   · agenda_vencida      : llamada agendada que no se hizo
--   · en_cola             : en horario y sin asesor (nadie en turno)
-- El atraso se mide desde el momento en que había que llamar (o desde la apertura, si fue antes).
-- SECURITY INVOKER: RLS decide qué ve cada uno (el supervisor, todo; el asesor, lo suyo).
CREATE FUNCTION rumbo.leads_sin_llamar()
RETURNS TABLE (lead_id bigint, telefono text, nombre_perfil text, asesor_id bigint, asesor text,
               motivo text, desde timestamptz, minutos integer)
LANGUAGE sql STABLE SET search_path = pg_catalog, rumbo AS $$
    WITH p AS (
        SELECT rumbo.config_int('minutos_alerta_supervisor', 30) AS umbral, rumbo.inicio_turno() AS apertura,
               rumbo.en_horario() AS abierto
    ), pendientes AS (
        SELECT l.id, l.telefono::text, l.nombre_perfil, l.asesor_id,
               CASE
                   WHEN l.estado_asignacion = 'en_cola' THEN 'en_cola'
                   WHEN l.intentos_totales = 0 THEN 'sin_primera_llamada'
                   WHEN EXISTS (SELECT 1 FROM rumbo.intento_llamada i
                                WHERE i.lead_id = l.id AND i.numero = l.intentos_totales
                                  AND i.agendado_para IS NOT NULL) THEN 'agenda_vencida'
                   ELSE 'reintento_vencido'
               END AS motivo,
               CASE WHEN l.estado_asignacion = 'en_cola' THEN l.primer_contacto_en
                    ELSE l.proxima_accion_en END AS vencio
        FROM rumbo.lead l
        WHERE (l.estado_asignacion = 'asignado' AND l.proxima_accion_en IS NOT NULL)
           OR l.estado_asignacion = 'en_cola'
    )
    SELECT x.id, x.telefono, x.nombre_perfil, x.asesor_id, u.nombre, x.motivo,
           greatest(x.vencio, p.apertura),
           (extract(epoch FROM now() - greatest(x.vencio, p.apertura)) / 60)::int
    FROM pendientes x CROSS JOIN p
    LEFT JOIN rumbo.asesor a ON a.id = x.asesor_id
    LEFT JOIN rumbo.usuario u ON u.id = a.usuario_id
    WHERE p.abierto
      AND greatest(x.vencio, p.apertura) < now() - make_interval(mins => p.umbral)
    ORDER BY greatest(x.vencio, p.apertura)
$$;

GRANT EXECUTE ON FUNCTION rumbo.inicio_turno(timestamptz), rumbo.agendar_llamada(bigint, integer, timestamptz),
                          rumbo.leads_sin_llamar() TO rumbo_app;
-- leads_sin_llamar corre con los permisos de quien la llama (para que aplique RLS) y lee el umbral.
-- La configuración ya es legible para cualquier usuario activo (RLS de 007).
GRANT EXECUTE ON FUNCTION rumbo.config_int(text, integer) TO rumbo_app;
