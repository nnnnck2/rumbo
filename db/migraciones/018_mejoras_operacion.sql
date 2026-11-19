-- 018 · Mejoras de operación y campañas (SCRUM-88 a SCRUM-100)
--   · SCRUM-89  Tope global de intentos sin contacto por lead (max_intentos_por_lead, 9 por defecto):
--               al alcanzarlo el lead se descarta solo con el motivo "Sin contacto".
--   · SCRUM-90  Cliente descartado que vuelve a escribir: el lead se reabre (etapa Nuevo) y se reparte.
--               Cliente con venta que vuelve a escribir: se avisa a su asesor (no cambia de etapa).
--   · SCRUM-88  rumbo.registrar_mensaje_automatico(): WhatsApp que envía el sistema (p. ej. "le llamamos
--               y no contestó") y clave aviso_no_contesta.
--   · SCRUM-91  rumbo.proxima_apertura(): cuándo abre la atención (para el texto de fuera de horario).
--   · SCRUM-92  rumbo.evento_conversion: bandeja de eventos para la Conversions API de Meta (cita / venta)
--               de los leads que llegaron desde un anuncio (tienen ctwa_clid).
--   · SCRUM-93  rumbo.exportacion: registro de cada exportación a CSV (quién, qué, cuántas filas).
--   · SCRUM-96/97  Claves guiones_llamada y metas_diarias.
--   · SCRUM-99  Inversión por anuncio (costo por lead y por venta).

-- ─────────────────────────────── Catálogos ───────────────────────────────

INSERT INTO rumbo.motivo_descarte (codigo, nombre) VALUES ('sin_contacto', 'Sin contacto tras varios intentos')
ON CONFLICT (codigo) DO NOTHING;

-- Reabrir un descartado como Nuevo (lo hace el sistema cuando el cliente vuelve a escribir).
INSERT INTO rumbo.etapa_transicion (desde, hacia) VALUES ('descartado', 'nuevo')
ON CONFLICT DO NOTHING;

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
    WHEN 'aviso_no_contesta' THEN
        -- {"activo": true, "texto": "...", "plantilla": "nombre_en_meta" | "", "idioma": "es", "horas_entre": 24}
        IF jsonb_typeof(v) <> 'object' OR NOT v ?& ARRAY['activo', 'texto', 'plantilla', 'idioma', 'horas_entre'] THEN
            RAISE EXCEPTION 'aviso_no_contesta requiere {activo, texto, plantilla, idioma, horas_entre}';
        END IF;
        IF jsonb_typeof(v -> 'activo') <> 'boolean' THEN
            RAISE EXCEPTION 'aviso_no_contesta.activo debe ser true o false';
        END IF;
        IF jsonb_typeof(v -> 'texto') <> 'string' OR length(v ->> 'texto') NOT BETWEEN 1 AND 1024 THEN
            RAISE EXCEPTION 'aviso_no_contesta.texto debe tener de 1 a 1024 caracteres';
        END IF;
        IF jsonb_typeof(v -> 'plantilla') <> 'string' OR (v ->> 'plantilla') !~ '^[a-z0-9_]*$'
           OR length(v ->> 'plantilla') > 512 THEN
            RAISE EXCEPTION 'aviso_no_contesta.plantilla: nombre de plantilla de Meta (minúsculas, números y _) o vacío';
        END IF;
        IF jsonb_typeof(v -> 'idioma') <> 'string' OR (v ->> 'idioma') !~ '^[a-z]{2}(_[A-Z]{2})?$' THEN
            RAISE EXCEPTION 'aviso_no_contesta.idioma: código como es o es_EC';
        END IF;
        IF jsonb_typeof(v -> 'horas_entre') <> 'number' OR (v ->> 'horas_entre')::int NOT BETWEEN 1 AND 168 THEN
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
    WHEN 'guiones_llamada' THEN
        -- {"General": "…", "Turismo": "…"}: un guion por tipo de visa.
        IF jsonb_typeof(v) <> 'object' OR pg_column_size(v) > 65536 THEN
            RAISE EXCEPTION 'guiones_llamada debe ser un objeto {tipo de visa: texto} de hasta 64 KB';
        END IF;
        FOR k, d IN SELECT * FROM jsonb_each(v) LOOP
            IF length(btrim(k)) NOT BETWEEN 1 AND 80 OR jsonb_typeof(d) <> 'string' OR length(d #>> '{}') > 4000 THEN
                RAISE EXCEPTION 'guiones_llamada: cada guion es un texto de hasta 4000 caracteres (tipo "%")', k;
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
    ('max_intentos_por_lead', '9',
     'SCRUM-89: intentos sin contacto (sumando todos los asesores) tras los que el lead se descarta solo.'),
    ('aviso_no_contesta',
     '{"activo": true, "horas_entre": 24, "plantilla": "", "idioma": "es",
       "texto": "Hola {nombre}, le saluda {asesor} de Multivisa. Le llamamos por su consulta de visa y no pudimos comunicarnos. ¿A qué hora le podemos llamar?"}',
     'SCRUM-88: WhatsApp al cliente cuando no contesta. Dentro de las 24 h de su último mensaje se envía el texto; '
     'después, la plantilla aprobada por Meta (si hay).'),
    ('metas_diarias', '{"llamadas": 20, "citas": 3, "ventas": 1}',
     'SCRUM-97: meta diaria de cada asesor.'),
    ('guiones_llamada',
     '{"General": "Saludar y presentarse: soy … de Multivisa.\nConfirmar el nombre y el país al que quiere viajar.\nPreguntar el tipo de visa y el motivo del viaje.\nPreguntar si ya tuvo visas o negaciones antes.\nExplicar el proceso y el costo.\nAgendar la cita o la próxima llamada."}',
     'SCRUM-96: guion de llamada por tipo de visa ("General" si el lead no tiene tipo).')
ON CONFLICT (clave) DO NOTHING;

-- ─────────────────────────────── SCRUM-89 · Tope de intentos por lead ───────────────────────────────

-- Intentos sin contacto del lead desde su última reapertura (un lead reabierto empieza de cero).
CREATE FUNCTION rumbo._intentos_sin_contacto(p_lead_id bigint) RETURNS integer
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
    SELECT count(*)::int
    FROM rumbo.intento_llamada i
    JOIN rumbo.resultado_llamada r ON r.codigo = i.resultado_codigo
    WHERE i.lead_id = p_lead_id AND r.cuenta_como_intento
      AND i.creado_en > coalesce((SELECT max(h.creado_en) FROM rumbo.lead_etapa_historial h
                                  WHERE h.lead_id = p_lead_id AND h.desde = 'descartado'), '-infinity')
$$;

CREATE OR REPLACE FUNCTION rumbo.registrar_intento(
    p_lead_id       bigint,
    p_version       integer,
    p_resultado     text,
    p_nota          text        DEFAULT NULL,
    p_agendar_para  timestamptz DEFAULT NULL,
    p_venta         jsonb       DEFAULT NULL)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_rol        rumbo.rol_usuario;
    v_lead       rumbo.lead;
    v_res        rumbo.resultado_llamada;
    v_destino    rumbo.etapa;
    v_actual     rumbo.etapa;
    v_max        integer := rumbo.config_int('max_intentos_por_asesor', 3);
    v_max_lead   integer := rumbo.config_int('max_intentos_por_lead', 9);
    v_espera     integer := rumbo.config_int('minutos_entre_reintentos', 30);
    v_fallidos   integer;
BEGIN
    v_rol := rumbo._exigir_rol('asesor', 'supervisor', 'admin');
    PERFORM rumbo._bloquear_reparto();
    v_lead := rumbo._tomar_lead(p_lead_id, p_version, v_rol);

    IF v_lead.estado_asignacion <> 'asignado' THEN
        RAISE EXCEPTION 'El lead % no está asignado (estado %)', p_lead_id, v_lead.estado_asignacion USING ERRCODE = 'RB422';
    END IF;

    SELECT * INTO v_res FROM rumbo.resultado_llamada WHERE codigo = p_resultado AND activo;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Resultado de llamada inválido: %', p_resultado USING ERRCODE = 'RB422';
    END IF;
    IF v_res.requiere_agenda AND (p_agendar_para IS NULL OR p_agendar_para <= now()) THEN
        RAISE EXCEPTION 'El resultado % requiere una fecha futura para la próxima llamada', p_resultado USING ERRCODE = 'RB422';
    END IF;
    IF v_res.requiere_venta AND (p_venta IS NULL OR jsonb_typeof(p_venta) <> 'object') THEN
        RAISE EXCEPTION 'El resultado % requiere los datos de la venta', p_resultado USING ERRCODE = 'RB422';
    END IF;

    INSERT INTO rumbo.intento_llamada (lead_id, asesor_id, numero, resultado_codigo, nota, agendado_para, registrado_por_usuario_id)
    VALUES (p_lead_id, v_lead.asesor_id, v_lead.intentos_totales + 1, p_resultado,
            nullif(btrim(p_nota), ''), p_agendar_para, rumbo.ctx_usuario_id());

    UPDATE rumbo.lead
    SET intentos_totales       = intentos_totales + 1,
        intentos_asesor_actual = intentos_asesor_actual + CASE WHEN v_res.cuenta_como_intento THEN 1 ELSE 0 END,
        proxima_accion_en      = CASE
                                    WHEN v_res.requiere_agenda     THEN p_agendar_para
                                    WHEN v_res.cuenta_como_intento THEN now() + make_interval(mins => v_espera)
                                    ELSE NULL
                                 END
    WHERE id = p_lead_id;

    -- Avance de etapa: solo hacia adelante o a una etapa final (nunca retrocede por un resultado).
    IF v_res.etapa_destino IS NOT NULL AND v_res.etapa_destino <> v_lead.etapa_codigo THEN
        SELECT * INTO v_destino FROM rumbo.etapa WHERE codigo = v_res.etapa_destino;
        SELECT * INTO v_actual  FROM rumbo.etapa WHERE codigo = v_lead.etapa_codigo;
        IF v_destino.es_final OR v_destino.orden > v_actual.orden THEN
            UPDATE rumbo.lead
            SET etapa_codigo = v_res.etapa_destino,
                motivo_descarte_codigo = v_res.motivo_descarte_codigo
            WHERE id = p_lead_id;
        END IF;
    END IF;

    IF v_res.requiere_venta THEN
        INSERT INTO rumbo.venta (lead_id, asesor_id, tipo_visa, pais, valor, moneda, registrada_por_usuario_id)
        VALUES (p_lead_id, v_lead.asesor_id,
                p_venta ->> 'tipo_visa',
                nullif(btrim(p_venta ->> 'pais'), ''),
                (p_venta ->> 'valor')::numeric(12,2),
                coalesce(upper(p_venta ->> 'moneda'), 'USD'),
                rumbo.ctx_usuario_id());
    END IF;

    IF v_res.cuenta_como_intento THEN
        -- SCRUM-89: tope global. Nadie logró contactarlo tras N intentos (entre todos los asesores) → descarte.
        v_fallidos := rumbo._intentos_sin_contacto(p_lead_id);
        IF v_fallidos >= v_max_lead THEN
            UPDATE rumbo.lead SET etapa_codigo = 'descartado', motivo_descarte_codigo = 'sin_contacto'
            WHERE id = p_lead_id;
            INSERT INTO rumbo.nota_lead (lead_id, autor_usuario_id, texto)
            VALUES (p_lead_id, rumbo.ctx_usuario_id(),
                    'Descartado automáticamente: ' || v_fallidos || ' intentos sin contacto (tope configurado: '
                    || v_max_lead || '). Si el cliente vuelve a escribir, el lead se reabre solo.');
        -- RF-23: al agotar los intentos del asesor el lead pasa al siguiente.
        ELSIF v_lead.intentos_asesor_actual + 1 >= v_max THEN
            PERFORM rumbo._repartir(p_lead_id, 'reintentos_agotados', v_lead.asesor_id);
        END IF;
    END IF;

    RETURN (SELECT l.version FROM rumbo.lead l WHERE l.id = p_lead_id);
END $$;

-- ─────────────────────────────── SCRUM-90 · El cliente vuelve a escribir ───────────────────────────────

CREATE OR REPLACE FUNCTION rumbo.registrar_mensaje_entrante(
    p_wa_message_id      text,
    p_telefono           text,
    p_nombre_perfil      text,
    p_numero_whatsapp_id smallint,
    p_tipo               text,
    p_cuerpo             text,
    p_payload            jsonb,
    p_ocurrido_en        timestamptz)
RETURNS TABLE (r_lead_id bigint, r_lead_nuevo boolean, r_mensaje_nuevo boolean, r_asesor_id bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_lead_id  bigint;
    v_nuevo    boolean;
    v_msg_id   bigint;
    v_lead     rumbo.lead;
    v_asesor_activo boolean;
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    PERFORM rumbo._bloquear_reparto();

    -- Igual que 012: el primer contacto es la hora real del mensaje más antiguo.
    INSERT INTO rumbo.lead AS l (telefono, nombre_perfil, numero_whatsapp_id, primer_contacto_en, ultimo_mensaje_en)
    VALUES (p_telefono, nullif(btrim(p_nombre_perfil), ''), p_numero_whatsapp_id,
            coalesce(p_ocurrido_en, now()), p_ocurrido_en)
    ON CONFLICT (telefono) DO UPDATE
        SET ultimo_mensaje_en  = greatest(l.ultimo_mensaje_en, EXCLUDED.ultimo_mensaje_en),
            primer_contacto_en = least(l.primer_contacto_en, EXCLUDED.primer_contacto_en),
            nombre_perfil      = coalesce(l.nombre_perfil, EXCLUDED.nombre_perfil)
    RETURNING l.id, (l.xmax = 0) INTO v_lead_id, v_nuevo;

    INSERT INTO rumbo.mensaje_whatsapp (lead_id, numero_whatsapp_id, wa_message_id, direccion, tipo, cuerpo, payload, ocurrido_en)
    VALUES (v_lead_id, p_numero_whatsapp_id, p_wa_message_id, 'entrante', coalesce(p_tipo, 'text'),
            p_cuerpo, coalesce(p_payload, '{}'::jsonb), p_ocurrido_en)
    ON CONFLICT (wa_message_id) DO NOTHING
    RETURNING id INTO v_msg_id;

    SELECT * INTO v_lead FROM rumbo.lead WHERE id = v_lead_id;

    IF v_msg_id IS NOT NULL THEN
        IF v_nuevo THEN
            PERFORM rumbo._repartir(v_lead_id, 'reparto');
        ELSIF v_lead.etapa_codigo = 'descartado' THEN
            -- SCRUM-90: un descartado que vuelve a escribir se reabre como Nuevo y entra al reparto.
            UPDATE rumbo.lead
            SET etapa_codigo = 'nuevo', asesor_id = NULL, asignado_en = NULL,
                intentos_asesor_actual = 0, proxima_accion_en = NULL
            WHERE id = v_lead_id;
            INSERT INTO rumbo.nota_lead (lead_id, autor_usuario_id, texto)
            VALUES (v_lead_id, 0, 'Reabierto automáticamente: el cliente volvió a escribir por WhatsApp '
                                  '(estaba descartado' || coalesce(' por «' || (SELECT m.nombre FROM rumbo.motivo_descarte m
                                                                          WHERE m.codigo = v_lead.motivo_descarte_codigo) || '»', '')
                                  || ').');
            PERFORM rumbo._repartir(v_lead_id, 'reparto');
        ELSIF v_lead.estado_asignacion = 'asignado' THEN
            -- RF-12: vuelve con su mismo asesor, salvo que ese asesor ya no esté activo.
            SELECT u.activo INTO v_asesor_activo
            FROM rumbo.asesor a JOIN rumbo.usuario u ON u.id = a.usuario_id
            WHERE a.id = v_lead.asesor_id;
            IF NOT v_asesor_activo THEN
                PERFORM rumbo._repartir(v_lead_id, 'asesor_inactivo', v_lead.asesor_id);
            END IF;
        END IF;
        -- Un cliente con venta (etapa Cerrado) no cambia: el aviso a su asesor lo da tg_avisar_mensaje.
    END IF;

    RETURN QUERY
    SELECT l.id, v_nuevo, v_msg_id IS NOT NULL, l.asesor_id FROM rumbo.lead l WHERE l.id = v_lead_id;
END $$;

-- El cliente vuelve a escribir: aviso a su asesor (como mucho uno cada 10 minutos por cliente).
-- 018: también si ya compró (lead cerrado con venta); en ese caso el aviso lo dice.
CREATE OR REPLACE FUNCTION rumbo.tg_avisar_mensaje() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_lead rumbo.lead;
    v_vendido boolean;
BEGIN
    IF NEW.direccion <> 'entrante' THEN
        RETURN NULL;
    END IF;
    SELECT * INTO v_lead FROM rumbo.lead WHERE id = NEW.lead_id;
    v_vendido := v_lead.etapa_codigo = 'cerrado';
    IF v_lead.asesor_id IS NOT NULL AND (v_lead.estado_asignacion = 'asignado' OR v_vendido) THEN
        PERFORM rumbo._avisar((SELECT usuario_id FROM rumbo.asesor WHERE id = v_lead.asesor_id), 'cliente_escribio',
                              rumbo._nombre_lead(NEW.lead_id)
                                  || CASE WHEN v_vendido THEN ' (cliente con venta) le escribió por WhatsApp'
                                          ELSE ' le escribió por WhatsApp' END,
                              coalesce(left(NEW.cuerpo, 140), '[' || NEW.tipo || ']'), NEW.lead_id,
                              'escribio:' || NEW.lead_id || ':' || floor(extract(epoch FROM NEW.ocurrido_en) / 600)::bigint);
    END IF;
    RETURN NULL;
END $$;

-- ─────────────────────────────── SCRUM-88 · Mensajes automáticos del sistema ───────────────────────────────

-- Registra un WhatsApp que envió el sistema (no un asesor) por el número de entrada del lead.
-- p_payload marca qué lo originó, p. ej. {"aviso_no_contesta": true, "intento": 4}.
CREATE FUNCTION rumbo.registrar_mensaje_automatico(p_lead_id bigint, p_wa_message_id text, p_cuerpo text,
                                                   p_tipo text DEFAULT 'text', p_payload jsonb DEFAULT '{}')
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_numero smallint;
    v_id     bigint;
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    SELECT l.numero_whatsapp_id INTO v_numero FROM rumbo.lead l WHERE l.id = p_lead_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'El lead % no existe', p_lead_id USING ERRCODE = 'no_data_found';
    END IF;
    IF v_numero IS NULL THEN
        RAISE EXCEPTION 'El lead % no tiene número de WhatsApp de entrada', p_lead_id USING ERRCODE = 'RB422';
    END IF;
    INSERT INTO rumbo.mensaje_whatsapp (lead_id, numero_whatsapp_id, wa_message_id, direccion, tipo, cuerpo,
                                        estado_entrega, payload, ocurrido_en)
    VALUES (p_lead_id, v_numero, p_wa_message_id, 'saliente', coalesce(p_tipo, 'text'), left(p_cuerpo, 4096),
            'enviado', coalesce(p_payload, '{}'::jsonb) || '{"automatica": true}', now())
    ON CONFLICT ON CONSTRAINT mensaje_wa_id_uk DO NOTHING
    RETURNING id INTO v_id;
    RETURN v_id;
END $$;

-- ─────────────────────────────── SCRUM-91 · Próxima apertura ───────────────────────────────

-- Momento en que abre la atención a partir de p_momento (p_momento mismo si ya está abierta).
-- NULL si no hay horario configurado.
CREATE FUNCTION rumbo.proxima_apertura(p_momento timestamptz DEFAULT now()) RETURNS timestamptz
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    c       jsonb;
    v_dia   date;
    v_abre  timestamptz;
BEGIN
    SELECT valor INTO c FROM rumbo.configuracion WHERE clave = 'horario';
    IF c IS NULL THEN
        RETURN NULL;
    END IF;
    IF rumbo.en_horario(p_momento) THEN
        RETURN p_momento;
    END IF;
    FOR i IN 0..7 LOOP
        v_dia := (p_momento AT TIME ZONE (c ->> 'zona'))::date + i;
        IF extract(isodow FROM v_dia)::int IN (SELECT (jsonb_array_elements_text(c -> 'dias'))::int) THEN
            v_abre := (v_dia + (c ->> 'inicio')::time) AT TIME ZONE (c ->> 'zona');
            IF v_abre > p_momento THEN
                RETURN v_abre;
            END IF;
        END IF;
    END LOOP;
    RETURN NULL;
END $$;

-- ─────────────────────────────── SCRUM-92 · Conversiones para Meta ───────────────────────────────

-- Bandeja (patrón outbox): un evento por lead y tipo. La llena un trigger al llegar a la etapa; un
-- worker los envía a la Conversions API. Solo leads que llegaron desde un anuncio (tienen ctwa_clid):
-- sin ese id Meta no puede atribuir el evento al anuncio.
CREATE TABLE rumbo.evento_conversion (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lead_id       bigint      NOT NULL REFERENCES rumbo.lead (id),
    evento        text        NOT NULL CHECK (evento IN ('Schedule', 'Purchase')),
    ctwa_clid     text        NOT NULL CHECK (length(ctwa_clid) BETWEEN 1 AND 500),
    ocurrido_en   timestamptz NOT NULL DEFAULT now(),
    estado        text        NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'enviado', 'error', 'vencido')),
    intentos      smallint    NOT NULL DEFAULT 0 CHECK (intentos >= 0),
    ultimo_error  text        CHECK (length(ultimo_error) <= 2000),
    enviado_en    timestamptz,
    creado_en     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT evento_conversion_uk UNIQUE (lead_id, evento)     -- una cita y una compra por lead
);
CREATE INDEX evento_conversion_pendiente_ix ON rumbo.evento_conversion (id) WHERE estado = 'pendiente';
CREATE TRIGGER evento_conversion_sin_truncate BEFORE TRUNCATE ON rumbo.evento_conversion
    FOR EACH STATEMENT EXECUTE FUNCTION rumbo.tg_sin_truncate();
ALTER TABLE rumbo.evento_conversion ENABLE ROW LEVEL SECURITY;
CREATE POLICY evento_conversion_leer ON rumbo.evento_conversion FOR SELECT TO rumbo_app
    USING ((SELECT rumbo.ctx_rol()) IN ('sistema', 'admin'));
GRANT SELECT ON rumbo.evento_conversion TO rumbo_app;

CREATE FUNCTION rumbo.tg_evento_conversion() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_clid text;
BEGIN
    IF NEW.hacia NOT IN ('cita_agendada', 'cerrado') THEN
        RETURN NULL;
    END IF;
    SELECT o.ctwa_clid INTO v_clid FROM rumbo.lead_origen o
    WHERE o.lead_id = NEW.lead_id AND o.ctwa_clid IS NOT NULL
    ORDER BY o.llegado_en, o.id LIMIT 1;
    IF v_clid IS NOT NULL THEN
        INSERT INTO rumbo.evento_conversion (lead_id, evento, ctwa_clid, ocurrido_en)
        VALUES (NEW.lead_id, CASE NEW.hacia WHEN 'cerrado' THEN 'Purchase' ELSE 'Schedule' END, v_clid, NEW.creado_en)
        ON CONFLICT ON CONSTRAINT evento_conversion_uk DO NOTHING;
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER etapa_evento_conversion AFTER INSERT ON rumbo.lead_etapa_historial
    FOR EACH ROW EXECUTE FUNCTION rumbo.tg_evento_conversion();

-- Toma eventos pendientes (SKIP LOCKED). Meta solo acepta eventos de los últimos 7 días: los más
-- viejos se marcan vencidos. El valor de la compra se lee al enviar (la venta se registra después
-- del cambio de etapa, en la misma transacción).
CREATE FUNCTION rumbo.tomar_eventos_conversion(p_cantidad integer DEFAULT 20)
RETURNS TABLE (id bigint, lead_id bigint, evento text, ctwa_clid text, ocurrido_en timestamptz,
               telefono text, valor numeric, moneda text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
#variable_conflict use_column
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    UPDATE rumbo.evento_conversion e SET estado = 'vencido', ultimo_error = 'Más de 7 días sin enviarse'
    WHERE e.estado = 'pendiente' AND e.ocurrido_en < now() - interval '7 days';
    RETURN QUERY
    WITH tomados AS (
        UPDATE rumbo.evento_conversion e SET intentos = e.intentos + 1
        WHERE e.id IN (SELECT x.id FROM rumbo.evento_conversion x
                       WHERE x.estado = 'pendiente' AND x.intentos < 8
                       ORDER BY x.id LIMIT least(greatest(p_cantidad, 1), 100)
                       FOR UPDATE SKIP LOCKED)
        RETURNING e.*)
    SELECT t.id, t.lead_id, t.evento, t.ctwa_clid, t.ocurrido_en, l.telefono::text,
           v.valor, v.moneda::text
    FROM tomados t
    JOIN rumbo.lead l ON l.id = t.lead_id
    LEFT JOIN LATERAL (SELECT s.valor, s.moneda FROM rumbo.venta s
                       WHERE s.lead_id = t.lead_id AND s.anulada_en IS NULL
                       ORDER BY s.cerrada_en DESC LIMIT 1) v ON t.evento = 'Purchase'
    ORDER BY t.id;
END $$;

CREATE FUNCTION rumbo.marcar_evento_conversion(p_id bigint, p_error text DEFAULT NULL, p_definitivo boolean DEFAULT false)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    UPDATE rumbo.evento_conversion
    SET estado       = CASE WHEN p_error IS NULL THEN 'enviado'
                            WHEN p_definitivo OR intentos >= 8 THEN 'error'
                            ELSE 'pendiente' END,
        enviado_en   = CASE WHEN p_error IS NULL THEN now() END,
        ultimo_error = left(p_error, 2000)
    WHERE id = p_id;
END $$;

-- ─────────────────────────────── SCRUM-99 · Inversión por anuncio ───────────────────────────────

ALTER TABLE rumbo.anuncio
    ADD COLUMN inversion numeric(12,2) CHECK (inversion >= 0),
    ADD COLUMN inversion_moneda char(3) NOT NULL DEFAULT 'USD' CHECK (inversion_moneda ~ '^[A-Z]{3}$');
COMMENT ON COLUMN rumbo.anuncio.inversion IS 'Lo invertido en el anuncio (total). Para costo por lead y por venta.';

CREATE FUNCTION rumbo.registrar_inversion_anuncio(p_anuncio_id bigint, p_inversion numeric)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    PERFORM rumbo._exigir_rol('admin');
    IF p_inversion IS NOT NULL AND p_inversion < 0 THEN
        RAISE EXCEPTION 'La inversión no puede ser negativa' USING ERRCODE = 'RB422';
    END IF;
    UPDATE rumbo.anuncio SET inversion = p_inversion, actualizado_en = now() WHERE id = p_anuncio_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'El anuncio % no existe', p_anuncio_id USING ERRCODE = 'no_data_found';
    END IF;
END $$;

-- ─────────────────────────────── SCRUM-93 · Registro de exportaciones ───────────────────────────────

CREATE TABLE rumbo.exportacion (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id  bigint      NOT NULL REFERENCES rumbo.usuario (id),
    que         text        NOT NULL CHECK (que IN ('leads', 'metricas')),
    filas       integer     NOT NULL CHECK (filas >= 0),
    filtros     jsonb       NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(filtros) = 'object' AND pg_column_size(filtros) < 4096),
    creado_en   timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER exportacion_inmutable BEFORE UPDATE OR DELETE ON rumbo.exportacion
    FOR EACH ROW EXECUTE FUNCTION rumbo.tg_solo_insercion();
CREATE TRIGGER exportacion_sin_truncate BEFORE TRUNCATE ON rumbo.exportacion
    FOR EACH STATEMENT EXECUTE FUNCTION rumbo.tg_sin_truncate();
ALTER TABLE rumbo.exportacion ENABLE ROW LEVEL SECURITY;
CREATE POLICY exportacion_leer ON rumbo.exportacion FOR SELECT TO rumbo_app
    USING ((SELECT rumbo.ctx_rol()) = 'admin');
GRANT SELECT ON rumbo.exportacion TO rumbo_app;

CREATE FUNCTION rumbo.registrar_exportacion(p_que text, p_filas integer, p_filtros jsonb DEFAULT '{}')
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_id bigint;
BEGIN
    PERFORM rumbo._exigir_rol('supervisor', 'admin');
    INSERT INTO rumbo.exportacion (usuario_id, que, filas, filtros)
    VALUES (rumbo.ctx_usuario_id(), p_que, p_filas, coalesce(p_filtros, '{}'::jsonb))
    RETURNING id INTO v_id;
    RETURN v_id;
END $$;

-- ─────────────────────────────── Permisos ───────────────────────────────

GRANT EXECUTE ON FUNCTION
    rumbo.registrar_mensaje_automatico(bigint, text, text, text, jsonb),
    rumbo.proxima_apertura(timestamptz),
    rumbo.tomar_eventos_conversion(integer),
    rumbo.marcar_evento_conversion(bigint, text, boolean),
    rumbo.registrar_inversion_anuncio(bigint, numeric),
    rumbo.registrar_exportacion(text, integer, jsonb)
TO rumbo_app;
