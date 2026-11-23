-- 023 · SCRUM-53 (RF-07) registro manual de leads y SCRUM-55 (RF-27) mensajes de seguimiento con plantillas
--   · Origen del lead: además de whatsapp/manual/referido/otro, 'llamada' (llamada entrante) y 'visita' (oficina).
--   · rumbo.registrar_lead_manual(): el asesor, supervisor o admin da de alta un cliente que llegó por otro canal.
--     Valida duplicados por número (si ya existe devuelve el existente y no crea nada). Según la configuración
--     "lead_manual" queda asignado a quien lo registró (si es asesor) o entra al reparto como uno de WhatsApp.
--   · Si ese cliente escribe después por WhatsApp, el lead toma el número de la empresa por el que escribió.
--   · Configuración nueva: lead_manual y plantillas_seguimiento (plantillas aprobadas por Meta que el asesor
--     envía desde la ficha; vienen DESACTIVADAS: fuera de la ventana de 24 h cada envío tiene costo).
--   · rumbo.registrar_mensaje_saliente() acepta un payload (p. ej. qué plantilla se envió).

-- ─────────────────────────────── Configuración (igual que 019 + dos claves) ───────────────────────────────

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
    WHEN 'lead_manual' THEN
        -- 023 · SCRUM-53: {"asignar_a_quien_registra": bool}
        IF jsonb_typeof(v) <> 'object' OR jsonb_typeof(v -> 'asignar_a_quien_registra') IS DISTINCT FROM 'boolean' THEN
            RAISE EXCEPTION 'lead_manual requiere {asignar_a_quien_registra: true|false}';
        END IF;
    WHEN 'plantillas_seguimiento' THEN
        -- 023 · SCRUM-55: {"activo": bool, "plantillas": [{"nombre", "titulo", "idioma", "variables": [...]}]}
        IF jsonb_typeof(v) <> 'object' OR jsonb_typeof(v -> 'activo') IS DISTINCT FROM 'boolean'
           OR jsonb_typeof(v -> 'plantillas') IS DISTINCT FROM 'array' OR jsonb_array_length(v -> 'plantillas') > 10 THEN
            RAISE EXCEPTION 'plantillas_seguimiento requiere {activo: true|false, plantillas: [hasta 10]}';
        END IF;
        FOR d IN SELECT * FROM jsonb_array_elements(v -> 'plantillas') LOOP
            IF jsonb_typeof(d) <> 'object' OR coalesce(d ->> 'nombre', '') !~ '^[a-z0-9_]+$' OR length(d ->> 'nombre') > 512
               OR length(btrim(coalesce(d ->> 'titulo', ''))) NOT BETWEEN 1 AND 80
               OR coalesce(d ->> 'idioma', '') !~ '^[a-z]{2}(_[A-Z]{2})?$'
               OR jsonb_typeof(coalesce(d -> 'variables', '[]')) <> 'array'
               OR jsonb_array_length(coalesce(d -> 'variables', '[]')) > 5
               OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(coalesce(d -> 'variables', '[]')) x
                          WHERE x NOT IN ('nombre', 'asesor', 'documentos', 'cita')) THEN
                RAISE EXCEPTION 'plantillas_seguimiento: plantilla inválida % (nombre en minúsculas, título, idioma y variables nombre/asesor/documentos/cita)', d;
            END IF;
        END LOOP;
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
    ('lead_manual', '{"asignar_a_quien_registra": true}',
     'SCRUM-53: el lead registrado a mano por un asesor queda con él (true) o entra al reparto (false).'),
    ('plantillas_seguimiento',
     '{"activo": false, "plantillas": [
        {"nombre": "lista_documentos", "titulo": "Lista de documentos", "idioma": "es", "variables": ["nombre", "documentos"]},
        {"nombre": "recordatorio_seguimiento", "titulo": "Recordatorio de seguimiento", "idioma": "es", "variables": ["nombre", "asesor"]}]}',
     'SCRUM-55: plantillas aprobadas por Meta para escribir fuera de la ventana de 24 h. Cada envío tiene costo: confirmar tarifas antes de activar.')
ON CONFLICT (clave) DO NOTHING;

-- ─────────────────────────────── Origen del lead ───────────────────────────────

ALTER TABLE rumbo.lead DROP CONSTRAINT lead_origen_check;
ALTER TABLE rumbo.lead ADD CONSTRAINT lead_origen_check
    CHECK (origen IN ('whatsapp', 'manual', 'referido', 'otro', 'llamada', 'visita'));

-- Un lead registrado a mano no tiene número de la empresa; si el cliente escribe después, toma ese número.
CREATE FUNCTION rumbo.tg_lead_numero_por_mensaje() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    IF NEW.direccion = 'entrante' THEN
        UPDATE rumbo.lead SET numero_whatsapp_id = NEW.numero_whatsapp_id
        WHERE id = NEW.lead_id AND numero_whatsapp_id IS NULL;
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER lead_numero_por_mensaje AFTER INSERT ON rumbo.mensaje_whatsapp
    FOR EACH ROW EXECUTE FUNCTION rumbo.tg_lead_numero_por_mensaje();

-- ─────────────────────────────── SCRUM-53 · Registro manual ───────────────────────────────

CREATE FUNCTION rumbo.registrar_lead_manual(p_telefono text, p_nombre text, p_origen text,
                                            p_tipo_visa text DEFAULT NULL, p_pais text DEFAULT NULL,
                                            p_nota text DEFAULT NULL)
RETURNS TABLE (r_lead_id bigint, r_nuevo boolean, r_asesor_id bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_rol     rumbo.rol_usuario := rumbo._exigir_rol('asesor', 'supervisor', 'admin');
    v_usuario bigint := rumbo.ctx_usuario_id();
    v_asesor  bigint := rumbo.ctx_asesor_id();
    v_lead    bigint;
    v_asignar boolean;
BEGIN
    IF p_origen NOT IN ('llamada', 'referido', 'visita', 'otro') THEN
        RAISE EXCEPTION 'Canal de origen inválido: %', p_origen USING ERRCODE = 'RB422';
    END IF;
    IF p_telefono IS NULL OR p_telefono !~ '^\+[1-9][0-9]{7,14}$' THEN
        RAISE EXCEPTION 'Teléfono inválido: use el formato internacional (+593…)' USING ERRCODE = 'RB422';
    END IF;
    PERFORM rumbo._bloquear_reparto();

    -- Duplicado por número: no se crea otro, se devuelve el que existe (la app decide qué mostrar).
    SELECT l.id INTO v_lead FROM rumbo.lead l WHERE l.telefono = p_telefono;
    IF FOUND THEN
        RETURN QUERY SELECT v_lead, false, (SELECT l.asesor_id FROM rumbo.lead l WHERE l.id = v_lead);
        RETURN;
    END IF;

    INSERT INTO rumbo.lead (telefono, nombre_perfil, origen, datos, primer_contacto_en, consentimiento_en)
    VALUES (p_telefono, nullif(left(btrim(coalesce(p_nombre, '')), 200), ''), p_origen,
            jsonb_strip_nulls(jsonb_build_object('tipo_visa', nullif(btrim(coalesce(p_tipo_visa, '')), ''),
                                                 'pais_interes', nullif(btrim(coalesce(p_pais, '')), ''),
                                                 'registrado_por', v_usuario)),
            now(), NULL)
    RETURNING id INTO v_lead;

    IF nullif(btrim(coalesce(p_nota, '')), '') IS NOT NULL THEN
        INSERT INTO rumbo.nota_lead (lead_id, autor_usuario_id, texto) VALUES (v_lead, v_usuario, left(btrim(p_nota), 4000));
    END IF;

    SELECT coalesce((c.valor ->> 'asignar_a_quien_registra')::boolean, true) INTO v_asignar
    FROM rumbo.configuracion c WHERE c.clave = 'lead_manual';
    v_asignar := coalesce(v_asignar, true);

    IF v_asignar AND v_rol = 'asesor' AND v_asesor IS NOT NULL THEN
        UPDATE rumbo.lead
        SET asesor_id = v_asesor, estado_asignacion = 'asignado', asignado_en = now(), proxima_accion_en = now()
        WHERE id = v_lead;
        INSERT INTO rumbo.asignacion (lead_id, asesor_anterior_id, asesor_id, motivo, asignado_por_usuario_id)
        VALUES (v_lead, NULL, v_asesor, 'manual', v_usuario);
    ELSE
        PERFORM rumbo._repartir(v_lead, 'reparto');
    END IF;

    RETURN QUERY SELECT v_lead, true, (SELECT l.asesor_id FROM rumbo.lead l WHERE l.id = v_lead);
END $$;

-- ─────────────────────────────── SCRUM-55 · Saliente con payload ───────────────────────────────

-- Firma nueva (con p_payload): se quita la anterior para que las llamadas con 3 o 4 argumentos no sean ambiguas.
DROP FUNCTION rumbo.registrar_mensaje_saliente(bigint, text, text, text);
CREATE FUNCTION rumbo.registrar_mensaje_saliente(p_lead_id bigint, p_wa_message_id text, p_cuerpo text,
                                                            p_tipo text DEFAULT 'text', p_payload jsonb DEFAULT '{}')
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_rol    rumbo.rol_usuario := rumbo._exigir_rol('asesor', 'supervisor', 'admin');
    v_lead   rumbo.lead := rumbo._tomar_lead(p_lead_id, NULL, v_rol);
    v_asesor bigint := rumbo.ctx_asesor_id();
    v_numero smallint;
    v_id     bigint;
BEGIN
    SELECT a.numero_whatsapp_id INTO v_numero FROM rumbo.asesor a WHERE a.id = coalesce(v_asesor, v_lead.asesor_id);
    IF v_numero IS NULL THEN
        RAISE EXCEPTION 'El asesor no tiene número de WhatsApp asignado' USING ERRCODE = 'RB422';
    END IF;
    INSERT INTO rumbo.mensaje_whatsapp (lead_id, numero_whatsapp_id, wa_message_id, direccion, tipo, cuerpo,
                                        enviado_por_asesor_id, estado_entrega, payload, ocurrido_en)
    VALUES (p_lead_id, v_numero, p_wa_message_id, 'saliente', p_tipo, p_cuerpo, v_asesor, 'enviado',
            coalesce(p_payload, '{}'), now())
    RETURNING id INTO v_id;
    RETURN v_id;
END $$;

GRANT EXECUTE ON FUNCTION rumbo.registrar_lead_manual(text, text, text, text, text, text),
                          rumbo.registrar_mensaje_saliente(bigint, text, text, text, jsonb) TO rumbo_app;
