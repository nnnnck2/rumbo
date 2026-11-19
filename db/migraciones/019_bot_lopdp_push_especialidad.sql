-- 019 · SCRUM-114 a SCRUM-130
--   · SCRUM-115  rumbo.guardar_dato_bot(): el bot de WhatsApp (rol sistema) guarda tipo de visa y destino
--                en el lead sin pisar lo que escribió el asesor.
--   · SCRUM-118  Reparto por especialidad: el asesor tiene preferencias {"paises": [...], "visas": [...]} y
--                _repartir prefiere a un especialista dentro de la vuelta (sin cambiar las demás reglas).
--   · SCRUM-120  rumbo.solicitud_lopdp: solicitudes de datos personales con plazo (15 días).
--   · SCRUM-122  rumbo.suscripcion_push + notificacion.push_en: notificaciones push (Web Push).
--   · Claves nuevas de configuración: bot_preguntas, recordatorio_cita, documentos_por_visa,
--     respuestas_rapidas, reporte_semanal, comision.

-- ─────────────────────────────── Configuración ───────────────────────────────

CREATE OR REPLACE FUNCTION rumbo.tg_validar_configuracion() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v jsonb := NEW.valor;
    d jsonb;
    k text;
BEGIN
    CASE NEW.clave
    WHEN 'horario' THEN
        IF jsonb_typeof(v) <> 'object' OR NOT v ?& ARRAY['inicio', 'fin', 'dias', 'zona'] THEN
            RAISE EXCEPTION 'horario requiere {inicio, fin, dias, zona}';
        END IF;
        IF (v ->> 'inicio')::time >= (v ->> 'fin')::time THEN
            RAISE EXCEPTION 'horario: inicio debe ser menor que fin';
        END IF;
        PERFORM now() AT TIME ZONE (v ->> 'zona');
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
    WHEN 'max_intentos_por_lead' THEN
        IF jsonb_typeof(v) <> 'number' OR v::int NOT BETWEEN 1 AND 30 THEN
            RAISE EXCEPTION 'max_intentos_por_lead debe ser un número entre 1 y 30';
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
    WHEN 'aviso_no_contesta', 'recordatorio_cita' THEN
        -- {"activo": bool, "texto": "...", "plantilla": "nombre_en_meta" | "", "idioma": "es", ...}
        IF jsonb_typeof(v) <> 'object' OR NOT v ?& ARRAY['activo', 'texto', 'plantilla', 'idioma'] THEN
            RAISE EXCEPTION '% requiere {activo, texto, plantilla, idioma}', NEW.clave;
        END IF;
        IF jsonb_typeof(v -> 'activo') <> 'boolean' THEN
            RAISE EXCEPTION '%.activo debe ser true o false', NEW.clave;
        END IF;
        IF jsonb_typeof(v -> 'texto') <> 'string' OR length(v ->> 'texto') NOT BETWEEN 1 AND 1024 THEN
            RAISE EXCEPTION '%.texto debe tener de 1 a 1024 caracteres', NEW.clave;
        END IF;
        IF jsonb_typeof(v -> 'plantilla') <> 'string' OR (v ->> 'plantilla') !~ '^[a-z0-9_]*$'
           OR length(v ->> 'plantilla') > 512 THEN
            RAISE EXCEPTION '%.plantilla: nombre de plantilla de Meta (minúsculas, números y _) o vacío', NEW.clave;
        END IF;
        IF jsonb_typeof(v -> 'idioma') <> 'string' OR (v ->> 'idioma') !~ '^[a-z]{2}(_[A-Z]{2})?$' THEN
            RAISE EXCEPTION '%.idioma: código como es o es_EC', NEW.clave;
        END IF;
        IF NEW.clave = 'aviso_no_contesta' AND (jsonb_typeof(v -> 'horas_entre') IS DISTINCT FROM 'number'
                                                OR (v ->> 'horas_entre')::int NOT BETWEEN 1 AND 168) THEN
            RAISE EXCEPTION 'aviso_no_contesta.horas_entre debe ser un número entre 1 y 168';
        END IF;
    WHEN 'metas_diarias' THEN
        IF jsonb_typeof(v) <> 'object' OR NOT v ?& ARRAY['llamadas', 'citas', 'ventas'] THEN
            RAISE EXCEPTION 'metas_diarias requiere {llamadas, citas, ventas}';
        END IF;
        FOREACH k IN ARRAY ARRAY['llamadas', 'citas', 'ventas'] LOOP
            IF jsonb_typeof(v -> k) <> 'number' OR (v ->> k)::int NOT BETWEEN 0 AND 1000 THEN
                RAISE EXCEPTION 'metas_diarias.% debe ser un número entre 0 y 1000', k;
            END IF;
        END LOOP;
    WHEN 'guiones_llamada', 'documentos_por_visa', 'respuestas_rapidas' THEN
        -- {"clave": "texto"}: guion / documentos (uno por línea) / respuesta rápida, por tipo de visa o título.
        IF jsonb_typeof(v) <> 'object' OR pg_column_size(v) > 65536 THEN
            RAISE EXCEPTION '% debe ser un objeto {nombre: texto} de hasta 64 KB', NEW.clave;
        END IF;
        FOR k, d IN SELECT * FROM jsonb_each(v) LOOP
            IF length(btrim(k)) NOT BETWEEN 1 AND 80 OR jsonb_typeof(d) <> 'string' OR length(d #>> '{}') > 4000 THEN
                RAISE EXCEPTION '%: cada texto es de hasta 4000 caracteres ("%")', NEW.clave, k;
            END IF;
        END LOOP;
    WHEN 'bot_preguntas' THEN
        IF jsonb_typeof(v) <> 'object' OR jsonb_typeof(v -> 'activo') IS DISTINCT FROM 'boolean' THEN
            RAISE EXCEPTION 'bot_preguntas requiere {activo: true|false, ...}';
        END IF;
        FOREACH k IN ARRAY ARRAY['texto_visa', 'texto_pais', 'texto_gracias'] LOOP
            IF jsonb_typeof(v -> k) <> 'string' OR length(v ->> k) NOT BETWEEN 1 AND 1024 THEN
                RAISE EXCEPTION 'bot_preguntas.% debe ser un texto de 1 a 1024 caracteres', k;
            END IF;
        END LOOP;
    WHEN 'reporte_semanal' THEN
        IF jsonb_typeof(v) <> 'object' OR jsonb_typeof(v -> 'destinatarios') IS DISTINCT FROM 'array'
           OR jsonb_array_length(v -> 'destinatarios') > 20 THEN
            RAISE EXCEPTION 'reporte_semanal requiere {destinatarios: [correos]} (máximo 20)';
        END IF;
        FOR d IN SELECT * FROM jsonb_array_elements(v -> 'destinatarios') LOOP
            IF jsonb_typeof(d) <> 'string' OR (d #>> '{}') !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' THEN
                RAISE EXCEPTION 'reporte_semanal: correo inválido %', d;
            END IF;
        END LOOP;
    WHEN 'comision' THEN
        IF jsonb_typeof(v) <> 'object' OR (v ->> 'tipo') NOT IN ('porcentaje', 'fijo')
           OR jsonb_typeof(v -> 'valor') <> 'number' OR (v ->> 'valor')::numeric < 0
           OR ((v ->> 'tipo') = 'porcentaje' AND (v ->> 'valor')::numeric > 100) THEN
            RAISE EXCEPTION 'comision requiere {tipo: porcentaje|fijo, valor >= 0} (porcentaje hasta 100)';
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
    ('bot_preguntas',
     '{"activo": false, "texto_visa": "Para atenderte mejor: ¿qué tipo de visa necesitas?",
       "texto_pais": "¿A qué país quieres viajar?",
       "texto_gracias": "¡Gracias! Un asesor te llamará pronto con esta información."}',
     'SCRUM-115: preguntas automáticas por WhatsApp antes de la llamada. PENDIENTE de validar con el área.'),
    ('recordatorio_cita',
     '{"activo": true, "plantilla": "", "idioma": "es",
       "texto": "Hola {nombre}, te recordamos tu cita con Multivisa el {cita}. Responde CONFIRMO o escríbenos si necesitas cambiarla."}',
     'SCRUM-116: recordatorio de la cita 24 h y 2 h antes.'),
    ('documentos_por_visa',
     '{"General": "Pasaporte vigente\nFoto tamaño pasaporte\nCédula de identidad", "Turismo": "Pasaporte vigente\nFoto tamaño pasaporte\nCertificado laboral o de estudios\nEstados de cuenta de los últimos 3 meses\nReserva de vuelo y hotel"}',
     'SCRUM-117: documentos que se piden por tipo de visa (uno por línea).'),
    ('respuestas_rapidas',
     '{"Saludo": "Hola {nombre}, le saluda {asesor} de Multivisa. ¿Tiene un momento para conversar sobre su visa?", "Pedir documentos": "Hola {nombre}, para avanzar con su trámite necesitamos: {documentos}", "Confirmar cita": "Hola {nombre}, le confirmamos su cita el {cita}. ¡Lo esperamos!"}',
     'SCRUM-114: mensajes listos para responder por WhatsApp desde la ficha.'),
    ('reporte_semanal', '{"destinatarios": []}', 'SCRUM-121: correos que reciben el reporte de los lunes.'),
    ('comision', '{"tipo": "porcentaje", "valor": 5}',
     'SCRUM-130: regla para ESTIMAR la comisión en Rumbo (la oficial la calcula CALLFLOW).')
ON CONFLICT (clave) DO NOTHING;

-- ─────────────────────────────── SCRUM-115 · Datos que responde el bot ───────────────────────────────

CREATE FUNCTION rumbo.guardar_dato_bot(p_lead_id bigint, p_clave text, p_valor text)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    IF p_clave NOT IN ('tipo_visa', 'pais_interes', 'bot_paso') THEN
        RAISE EXCEPTION 'Dato del bot no permitido: %', p_clave USING ERRCODE = 'RB422';
    END IF;
    IF length(btrim(coalesce(p_valor, ''))) NOT BETWEEN 1 AND 80 THEN
        RAISE EXCEPTION 'Valor inválido para %', p_clave USING ERRCODE = 'RB422';
    END IF;
    UPDATE rumbo.lead
    SET datos = datos || jsonb_build_object(p_clave, btrim(p_valor))
                      || CASE WHEN p_clave <> 'bot_paso' THEN jsonb_build_object('respondio_bot', true) ELSE '{}'::jsonb END
    WHERE id = p_lead_id
      -- lo que escribió el asesor (o la campaña) no se pisa; el paso del bot sí avanza
      AND (p_clave = 'bot_paso' OR coalesce(btrim(datos ->> p_clave), '') = '');
    RETURN FOUND;
END $$;

-- ─────────────────────────────── SCRUM-118 · Especialidad del asesor ───────────────────────────────

CREATE FUNCTION rumbo._es_especialista(p_pref jsonb, p_visa text, p_pais text) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
    SELECT EXISTS (SELECT 1 FROM jsonb_array_elements_text(coalesce(p_pref -> 'visas', '[]')) x
                   WHERE lower(x) = lower(btrim(p_visa)))
        OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(coalesce(p_pref -> 'paises', '[]')) x
                   WHERE lower(x) = lower(btrim(p_pais)))
$$;

-- Igual que 015, con un criterio más en el paso 1: entre los que aún no lo tuvieron en esta vuelta,
-- primero el especialista en el tipo de visa o país del lead.
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
        SELECT a.id INTO v_asesor
        FROM rumbo.asesor a
        JOIN rumbo.usuario u ON u.id = a.usuario_id
        WHERE u.activo AND a.estado IN ('disponible', 'ocupado')
          AND a.id <> ALL (v_ya)
          AND a.id IS DISTINCT FROM p_excluir
        ORDER BY (a.estado <> 'disponible'),
                 NOT rumbo._es_especialista(a.preferencias, v_lead.tipo_visa, v_lead.pais_interes),
                 a.ultimo_lead_en NULLS FIRST, a.id
        LIMIT 1
        FOR UPDATE OF a;

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
    UPDATE rumbo.asesor SET ultimo_lead_en = clock_timestamp() WHERE id = v_asesor;
    INSERT INTO rumbo.asignacion (lead_id, asesor_anterior_id, asesor_id, motivo, asignado_por_usuario_id, vuelta)
    VALUES (p_lead_id, v_lead.asesor_id, v_asesor, p_motivo, rumbo.ctx_usuario_id(), v_vuelta);
    RETURN v_asesor;
END $$;

-- El admin guarda las especialidades de un asesor (en preferencias, sin tocar el resto).
CREATE FUNCTION rumbo.guardar_especialidades(p_asesor_id bigint, p_paises text[], p_visas text[])
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    PERFORM rumbo._exigir_rol('admin');
    UPDATE rumbo.asesor
    SET preferencias = preferencias || jsonb_build_object('paises', to_jsonb(coalesce(p_paises, '{}')),
                                                          'visas', to_jsonb(coalesce(p_visas, '{}')))
    WHERE id = p_asesor_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'El asesor % no existe', p_asesor_id USING ERRCODE = 'no_data_found';
    END IF;
END $$;

-- ─────────────────────────────── SCRUM-120 · Solicitudes LOPDP ───────────────────────────────

CREATE TABLE rumbo.solicitud_lopdp (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lead_id               bigint      NOT NULL REFERENCES rumbo.lead (id),
    tipo                  text        NOT NULL CHECK (tipo IN ('acceso', 'rectificacion', 'eliminacion', 'oposicion')),
    detalle               text        CHECK (length(detalle) <= 2000),
    recibida_en           date        NOT NULL,
    vence_en              date        NOT NULL,
    estado                text        NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'atendida', 'rechazada')),
    respuesta             text        CHECK (length(respuesta) <= 2000),
    registrada_por        bigint      NOT NULL REFERENCES rumbo.usuario (id),
    atendida_por          bigint      REFERENCES rumbo.usuario (id),
    atendida_en           timestamptz,
    creado_en             timestamptz NOT NULL DEFAULT now(),
    CHECK ((estado = 'pendiente') = (atendida_en IS NULL)),
    CHECK (vence_en >= recibida_en)
);
CREATE INDEX solicitud_lopdp_pendiente_ix ON rumbo.solicitud_lopdp (vence_en) WHERE estado = 'pendiente';
CREATE TRIGGER solicitud_lopdp_sin_borrado BEFORE DELETE ON rumbo.solicitud_lopdp
    FOR EACH ROW EXECUTE FUNCTION rumbo.tg_solo_insercion();
CREATE TRIGGER solicitud_lopdp_sin_truncate BEFORE TRUNCATE ON rumbo.solicitud_lopdp
    FOR EACH STATEMENT EXECUTE FUNCTION rumbo.tg_sin_truncate();
CREATE TRIGGER auditar AFTER INSERT OR UPDATE OR DELETE ON rumbo.solicitud_lopdp
    FOR EACH ROW EXECUTE FUNCTION auditoria.tg_registrar('', 'detalle,respuesta');
ALTER TABLE rumbo.solicitud_lopdp ENABLE ROW LEVEL SECURITY;
CREATE POLICY solicitud_lopdp_leer ON rumbo.solicitud_lopdp FOR SELECT TO rumbo_app
    USING ((SELECT rumbo.ctx_rol()) = 'admin');
GRANT SELECT ON rumbo.solicitud_lopdp TO rumbo_app;

-- Plazo: 15 días desde que se recibió (configurable en el futuro si el área lo define distinto).
CREATE FUNCTION rumbo.registrar_solicitud_lopdp(p_lead_id bigint, p_tipo text, p_recibida_en date, p_detalle text DEFAULT NULL)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_id bigint;
BEGIN
    PERFORM rumbo._exigir_rol('admin');
    IF p_recibida_en IS NULL OR p_recibida_en > current_date THEN
        RAISE EXCEPTION 'La fecha de recepción no puede ser futura' USING ERRCODE = 'RB422';
    END IF;
    INSERT INTO rumbo.solicitud_lopdp (lead_id, tipo, detalle, recibida_en, vence_en, registrada_por)
    VALUES (p_lead_id, p_tipo, nullif(btrim(p_detalle), ''), p_recibida_en, p_recibida_en + 15, rumbo.ctx_usuario_id())
    RETURNING id INTO v_id;
    RETURN v_id;
END $$;

CREATE FUNCTION rumbo.atender_solicitud_lopdp(p_id bigint, p_estado text, p_respuesta text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    PERFORM rumbo._exigir_rol('admin');
    IF p_estado NOT IN ('atendida', 'rechazada') THEN
        RAISE EXCEPTION 'Estado inválido: %', p_estado USING ERRCODE = 'RB422';
    END IF;
    IF length(btrim(coalesce(p_respuesta, ''))) < 3 THEN
        RAISE EXCEPTION 'Escriba qué se respondió al cliente' USING ERRCODE = 'RB422';
    END IF;
    UPDATE rumbo.solicitud_lopdp
    SET estado = p_estado, respuesta = btrim(p_respuesta), atendida_por = rumbo.ctx_usuario_id(), atendida_en = now()
    WHERE id = p_id AND estado = 'pendiente';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'La solicitud % no existe o ya fue atendida', p_id USING ERRCODE = 'RB422';
    END IF;
END $$;

-- ─────────────────────────────── SCRUM-122 · Notificaciones push ───────────────────────────────

CREATE TABLE rumbo.suscripcion_push (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id  bigint      NOT NULL REFERENCES rumbo.usuario (id),
    endpoint    text        NOT NULL UNIQUE CHECK (endpoint ~ '^https://' AND length(endpoint) <= 1000),
    p256dh      text        NOT NULL CHECK (length(p256dh) BETWEEN 20 AND 200),
    auth        text        NOT NULL CHECK (length(auth) BETWEEN 8 AND 100),
    agente      text        CHECK (length(agente) <= 300),
    creado_en   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX suscripcion_push_usuario_ix ON rumbo.suscripcion_push (usuario_id);
ALTER TABLE rumbo.suscripcion_push ENABLE ROW LEVEL SECURITY;
CREATE POLICY suscripcion_push_propias ON rumbo.suscripcion_push FOR SELECT TO rumbo_app
    USING (usuario_id = (SELECT rumbo.ctx_usuario_id()));
GRANT SELECT ON rumbo.suscripcion_push TO rumbo_app;

ALTER TABLE rumbo.notificacion ADD COLUMN push_en timestamptz;
CREATE INDEX notificacion_push_ix ON rumbo.notificacion (id) WHERE push_en IS NULL;

-- El usuario guarda (o actualiza) la suscripción de este dispositivo.
CREATE FUNCTION rumbo.guardar_suscripcion_push(p_endpoint text, p_p256dh text, p_auth text, p_agente text DEFAULT NULL)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    PERFORM rumbo._exigir_rol('asesor', 'supervisor', 'admin');
    INSERT INTO rumbo.suscripcion_push (usuario_id, endpoint, p256dh, auth, agente)
    VALUES (rumbo.ctx_usuario_id(), p_endpoint, p_p256dh, p_auth, left(p_agente, 300))
    ON CONFLICT (endpoint) DO UPDATE
        SET usuario_id = EXCLUDED.usuario_id, p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth, agente = EXCLUDED.agente;
END $$;

-- Quita una suscripción: el propio usuario (al desactivar) o el sistema (si el navegador la dio de baja).
CREATE FUNCTION rumbo.borrar_suscripcion_push(p_endpoint text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_rol rumbo.rol_usuario := rumbo._exigir_rol('asesor', 'supervisor', 'admin', 'sistema');
BEGIN
    DELETE FROM rumbo.suscripcion_push
    WHERE endpoint = p_endpoint AND (v_rol = 'sistema' OR usuario_id = rumbo.ctx_usuario_id());
END $$;

-- Toma las notificaciones recientes aún no enviadas por push, con las suscripciones de su usuario.
-- Se marcan como enviadas al tomarlas (como mucho una vez: un aviso viejo no tiene sentido reintentarlo).
CREATE FUNCTION rumbo.tomar_notificaciones_push(p_cantidad integer DEFAULT 50)
RETURNS TABLE (id bigint, titulo text, mensaje text, url text, suscripciones jsonb)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
#variable_conflict use_column
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    RETURN QUERY
    WITH tomadas AS (
        UPDATE rumbo.notificacion n SET push_en = now()
        WHERE n.id IN (SELECT x.id FROM rumbo.notificacion x
                       WHERE x.push_en IS NULL AND x.leida_en IS NULL AND x.creado_en > now() - interval '15 minutes'
                         AND EXISTS (SELECT 1 FROM rumbo.suscripcion_push s WHERE s.usuario_id = x.usuario_id)
                       ORDER BY x.id LIMIT least(greatest(p_cantidad, 1), 200)
                       FOR UPDATE SKIP LOCKED)
        RETURNING n.*)
    SELECT t.id, t.titulo, t.mensaje, t.url,
           (SELECT jsonb_agg(jsonb_build_object('endpoint', s.endpoint, 'p256dh', s.p256dh, 'auth', s.auth))
            FROM rumbo.suscripcion_push s WHERE s.usuario_id = t.usuario_id)
    FROM tomadas t ORDER BY t.id;
END $$;

-- ─────────────────────────────── Permisos ───────────────────────────────

GRANT EXECUTE ON FUNCTION
    rumbo.guardar_dato_bot(bigint, text, text),
    rumbo.guardar_especialidades(bigint, text[], text[]),
    rumbo.registrar_solicitud_lopdp(bigint, text, date, text),
    rumbo.atender_solicitud_lopdp(bigint, text, text),
    rumbo.guardar_suscripcion_push(text, text, text, text),
    rumbo.borrar_suscripcion_push(text),
    rumbo.tomar_notificaciones_push(integer)
TO rumbo_app;
