-- 006 · Contexto de sesión y operaciones de negocio
--
-- CONTEXTO: en cada transacción la app ejecuta
--     SELECT set_config('rumbo.usuario_id', '<id de auth_user>', true);   -- true = solo esta transacción
-- El rol y el asesor NO vienen de la app: se leen de rumbo.usuario. Sin contexto (o con un
-- usuario inactivo) las políticas RLS no devuelven nada: la base falla cerrada.
--
-- CONCURRENCIA Y BLOQUEOS — jerarquía fija para que no haya deadlocks:
--     1) candado de reparto  (pg_advisory_xact_lock, uno solo para todo el sistema)
--     2) filas de lead       (SELECT ... FOR UPDATE, en orden de id)
--     3) filas de asesor     (SELECT ... FOR UPDATE)
-- Toda función que cambie la asignación de un lead toma el candado 1 ANTES de tocar filas.
-- Con 10 asesores y ~15 leads/día el candado único no genera espera apreciable y da un
-- round robin exacto (sin asignaciones dobles ni saltos).
--
-- Las funciones son SECURITY DEFINER (corren como rumbo_owner) y validan el rol del
-- usuario al inicio: la app no puede escribir directamente en las columnas de asignación,
-- etapa, intentos ni ventas; solo a través de estas funciones.

-- ─────────────────────────────── Contexto ───────────────────────────────

CREATE FUNCTION rumbo.ctx_usuario_id() RETURNS bigint
LANGUAGE sql STABLE PARALLEL SAFE SET search_path = pg_catalog AS $$
    SELECT nullif(current_setting('rumbo.usuario_id', true), '')::bigint
$$;

CREATE FUNCTION rumbo.ctx_rol() RETURNS rumbo.rol_usuario
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
    SELECT u.rol FROM rumbo.usuario u WHERE u.id = rumbo.ctx_usuario_id() AND u.activo
$$;

CREATE FUNCTION rumbo.ctx_asesor_id() RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
    SELECT a.id
    FROM rumbo.asesor a
    JOIN rumbo.usuario u ON u.id = a.usuario_id
    WHERE u.id = rumbo.ctx_usuario_id() AND u.activo
$$;

CREATE FUNCTION rumbo._exigir_rol(VARIADIC p_roles rumbo.rol_usuario[]) RETURNS rumbo.rol_usuario
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_rol rumbo.rol_usuario := rumbo.ctx_rol();
BEGIN
    IF v_rol IS NULL THEN
        RAISE EXCEPTION 'Sin contexto de usuario activo (rumbo.usuario_id)' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NOT (v_rol = ANY (p_roles)) THEN
        RAISE EXCEPTION 'El rol % no puede realizar esta acción', v_rol USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN v_rol;
END $$;

CREATE FUNCTION rumbo._bloquear_reparto() RETURNS void
LANGUAGE sql SET search_path = pg_catalog AS $$
    SELECT pg_advisory_xact_lock(7240001)     -- se libera solo al terminar la transacción
$$;

-- ─────────────────────────────── Configuración ───────────────────────────────

CREATE FUNCTION rumbo.config_int(p_clave text, p_defecto integer) RETURNS integer
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
    SELECT coalesce((SELECT (c.valor)::int FROM rumbo.configuracion c WHERE c.clave = p_clave), p_defecto)
$$;

CREATE FUNCTION rumbo.en_horario(p_momento timestamptz DEFAULT now()) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    c       jsonb;
    v_local timestamp;
BEGIN
    SELECT valor INTO c FROM rumbo.configuracion WHERE clave = 'horario';
    IF c IS NULL THEN
        RETURN true;
    END IF;
    v_local := p_momento AT TIME ZONE (c ->> 'zona');
    RETURN extract(isodow FROM v_local)::int IN (SELECT (jsonb_array_elements_text(c -> 'dias'))::int)
       AND v_local::time >= (c ->> 'inicio')::time
       AND v_local::time <  (c ->> 'fin')::time;
END $$;

-- ─────────────────────────────── Reparto (interno) ───────────────────────────────

-- Asigna el lead al siguiente asesor. Orden de preferencia:
--   1) no es el asesor a excluir (el que agotó intentos o no llamó a tiempo)
--   2) disponible antes que ocupado (si todos están ocupados igual se asigna: el lead no se pierde)
--   3) el que hace más tiempo recibió un lead (round robin)
-- Si no hay nadie en turno o es fuera de horario, el lead queda en cola.
CREATE FUNCTION rumbo._repartir(p_lead_id bigint, p_motivo rumbo.motivo_asignacion, p_excluir bigint DEFAULT NULL)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_lead   rumbo.lead;
    v_asesor bigint;
BEGIN
    PERFORM rumbo._bloquear_reparto();

    SELECT * INTO v_lead FROM rumbo.lead WHERE id = p_lead_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'El lead % no existe', p_lead_id USING ERRCODE = 'no_data_found';
    END IF;
    IF v_lead.estado_asignacion = 'cerrado' THEN
        RAISE EXCEPTION 'El lead % está cerrado', p_lead_id USING ERRCODE = 'RB422';
    END IF;

    IF rumbo.en_horario() THEN
        SELECT a.id INTO v_asesor
        FROM rumbo.asesor a
        JOIN rumbo.usuario u ON u.id = a.usuario_id
        WHERE u.activo AND a.estado IN ('disponible', 'ocupado')
        ORDER BY (a.id IS NOT DISTINCT FROM p_excluir),
                 (a.estado <> 'disponible'),
                 a.ultimo_lead_en NULLS FIRST,
                 a.id
        LIMIT 1
        FOR UPDATE OF a;
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

    INSERT INTO rumbo.asignacion (lead_id, asesor_anterior_id, asesor_id, motivo, asignado_por_usuario_id)
    VALUES (p_lead_id, v_lead.asesor_id, v_asesor, p_motivo, rumbo.ctx_usuario_id());

    RETURN v_asesor;
END $$;

-- Bloquea el lead y verifica permisos + versión (bloqueo optimista).
CREATE FUNCTION rumbo._tomar_lead(p_lead_id bigint, p_version integer, p_rol rumbo.rol_usuario)
RETURNS rumbo.lead
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_lead rumbo.lead;
BEGIN
    SELECT * INTO v_lead FROM rumbo.lead WHERE id = p_lead_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'El lead % no existe', p_lead_id USING ERRCODE = 'no_data_found';
    END IF;
    IF p_rol = 'asesor' AND v_lead.asesor_id IS DISTINCT FROM rumbo.ctx_asesor_id() THEN
        RAISE EXCEPTION 'El lead % no está asignado a usted', p_lead_id USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_version IS NOT NULL AND p_version <> v_lead.version THEN
        RAISE EXCEPTION 'El lead % fue modificado por otro usuario (versión % ≠ %). Recargue la ficha.',
            p_lead_id, p_version, v_lead.version USING ERRCODE = 'RB409';
    END IF;
    RETURN v_lead;
END $$;

-- ─────────────────────────────── Webhook / mensajes ───────────────────────────────

-- Guarda el evento crudo del webhook (idempotente). El endpoint responde 200 en cuanto esto termina.
CREATE FUNCTION rumbo.recibir_evento_webhook(p_idempotencia text, p_firma_valida boolean, p_payload jsonb)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_id bigint;
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    INSERT INTO rumbo.webhook_evento (idempotencia, firma_valida, payload)
    VALUES (p_idempotencia, p_firma_valida, p_payload)
    ON CONFLICT (idempotencia) DO NOTHING
    RETURNING id INTO v_id;
    RETURN v_id;                                   -- NULL = evento repetido
END $$;

-- Toma eventos pendientes para un worker. SKIP LOCKED: varios workers en paralelo nunca
-- toman el mismo evento ni se bloquean entre sí.
CREATE FUNCTION rumbo.tomar_eventos_webhook(p_cantidad integer DEFAULT 10)
RETURNS SETOF rumbo.webhook_evento
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    RETURN QUERY
    UPDATE rumbo.webhook_evento w
    SET intentos = w.intentos + 1
    WHERE w.id IN (
        SELECT e.id FROM rumbo.webhook_evento e
        WHERE e.procesado_en IS NULL AND e.firma_valida AND e.intentos < 10
        ORDER BY e.id
        LIMIT least(greatest(p_cantidad, 1), 100)
        FOR UPDATE SKIP LOCKED)
    RETURNING w.*;
END $$;

CREATE FUNCTION rumbo.marcar_evento_webhook(p_evento_id bigint, p_error text DEFAULT NULL)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    UPDATE rumbo.webhook_evento
    SET procesado_en = CASE WHEN p_error IS NULL THEN now() END,
        ultimo_error = left(p_error, 2000)
    WHERE id = p_evento_id;
END $$;

-- Registra un mensaje entrante: crea o actualiza el lead (sin duplicados), guarda el
-- mensaje (idempotente por wa_message_id) y reparte si el lead es nuevo (RF-03, RF-10, RF-12).
CREATE FUNCTION rumbo.registrar_mensaje_entrante(
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

    INSERT INTO rumbo.lead AS l (telefono, nombre_perfil, numero_whatsapp_id, ultimo_mensaje_en)
    VALUES (p_telefono, nullif(btrim(p_nombre_perfil), ''), p_numero_whatsapp_id, p_ocurrido_en)
    ON CONFLICT (telefono) DO UPDATE
        SET ultimo_mensaje_en = greatest(l.ultimo_mensaje_en, EXCLUDED.ultimo_mensaje_en),
            nombre_perfil     = coalesce(l.nombre_perfil, EXCLUDED.nombre_perfil)
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
        ELSIF v_lead.estado_asignacion = 'asignado' THEN
            -- RF-12: vuelve con su mismo asesor, salvo que ese asesor ya no esté activo.
            SELECT u.activo INTO v_asesor_activo
            FROM rumbo.asesor a JOIN rumbo.usuario u ON u.id = a.usuario_id
            WHERE a.id = v_lead.asesor_id;
            IF NOT v_asesor_activo THEN
                PERFORM rumbo._repartir(v_lead_id, 'asesor_inactivo', v_lead.asesor_id);
            END IF;
        END IF;
    END IF;

    RETURN QUERY
    SELECT l.id, v_nuevo, v_msg_id IS NOT NULL, l.asesor_id FROM rumbo.lead l WHERE l.id = v_lead_id;
END $$;

-- Mensaje saliente desde el número asignado al asesor (SCRUM-59).
CREATE FUNCTION rumbo.registrar_mensaje_saliente(p_lead_id bigint, p_wa_message_id text, p_cuerpo text, p_tipo text DEFAULT 'text')
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
                                        enviado_por_asesor_id, estado_entrega, ocurrido_en)
    VALUES (p_lead_id, v_numero, p_wa_message_id, 'saliente', p_tipo, p_cuerpo, v_asesor, 'enviado', now())
    RETURNING id INTO v_id;
    RETURN v_id;
END $$;

-- ─────────────────────────────── Llamadas ───────────────────────────────

-- Registra el resultado de una llamada y ejecuta la acción correspondiente (RF-22, RF-23, RF-24).
-- Devuelve la nueva versión del lead.
CREATE FUNCTION rumbo.registrar_intento(
    p_lead_id       bigint,
    p_version       integer,
    p_resultado     text,
    p_nota          text        DEFAULT NULL,
    p_agendar_para  timestamptz DEFAULT NULL,
    p_venta         jsonb       DEFAULT NULL)     -- {"tipo_visa": "...", "valor": 1200, "moneda": "USD", "pais": "..."}
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_rol        rumbo.rol_usuario;
    v_lead       rumbo.lead;
    v_res        rumbo.resultado_llamada;
    v_destino    rumbo.etapa;
    v_actual     rumbo.etapa;
    v_max        integer := rumbo.config_int('max_intentos_por_asesor', 3);
    v_espera     integer := rumbo.config_int('minutos_entre_reintentos', 30);
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

    -- RF-23: al agotar los intentos el lead pasa al siguiente asesor. Nunca se cierra por falta de contacto.
    IF v_res.cuenta_como_intento AND v_lead.intentos_asesor_actual + 1 >= v_max THEN
        PERFORM rumbo._repartir(p_lead_id, 'reintentos_agotados', v_lead.asesor_id);
    END IF;

    RETURN (SELECT l.version FROM rumbo.lead l WHERE l.id = p_lead_id);
END $$;

-- Cambio manual de etapa desde la ficha (RF-25).
CREATE FUNCTION rumbo.cambiar_etapa(p_lead_id bigint, p_version integer, p_etapa text, p_motivo_descarte text DEFAULT NULL)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_rol  rumbo.rol_usuario;
    v_lead rumbo.lead;
BEGIN
    v_rol := rumbo._exigir_rol('asesor', 'supervisor', 'admin');
    PERFORM rumbo._bloquear_reparto();
    v_lead := rumbo._tomar_lead(p_lead_id, p_version, v_rol);

    UPDATE rumbo.lead
    SET etapa_codigo = p_etapa,
        motivo_descarte_codigo = CASE WHEN p_etapa = 'descartado' THEN p_motivo_descarte END
    WHERE id = p_lead_id;

    -- Un descartado reabierto sin asesor vuelve al reparto.
    IF (SELECT l.estado_asignacion FROM rumbo.lead l WHERE l.id = p_lead_id) = 'en_cola' THEN
        PERFORM rumbo._repartir(p_lead_id, 'reparto');
    END IF;

    RETURN (SELECT l.version FROM rumbo.lead l WHERE l.id = p_lead_id);
END $$;

-- ─────────────────────────────── Supervisor / asesor ───────────────────────────────

CREATE FUNCTION rumbo.reasignar_manual(p_lead_id bigint, p_asesor_id bigint)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_lead rumbo.lead;
BEGIN
    PERFORM rumbo._exigir_rol('supervisor', 'admin');
    PERFORM rumbo._bloquear_reparto();
    v_lead := rumbo._tomar_lead(p_lead_id, NULL, 'supervisor');

    IF v_lead.estado_asignacion = 'cerrado' THEN
        RAISE EXCEPTION 'El lead % está cerrado', p_lead_id USING ERRCODE = 'RB422';
    END IF;
    PERFORM 1 FROM rumbo.asesor a JOIN rumbo.usuario u ON u.id = a.usuario_id
    WHERE a.id = p_asesor_id AND u.activo
    FOR UPDATE OF a;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'El asesor % no existe o está inactivo', p_asesor_id USING ERRCODE = 'RB422';
    END IF;

    UPDATE rumbo.lead
    SET asesor_id = p_asesor_id, estado_asignacion = 'asignado', asignado_en = now(),
        intentos_asesor_actual = 0, proxima_accion_en = now()
    WHERE id = p_lead_id;
    UPDATE rumbo.asesor SET ultimo_lead_en = clock_timestamp() WHERE id = p_asesor_id;
    INSERT INTO rumbo.asignacion (lead_id, asesor_anterior_id, asesor_id, motivo, asignado_por_usuario_id)
    VALUES (p_lead_id, v_lead.asesor_id, p_asesor_id, 'manual', rumbo.ctx_usuario_id());
END $$;

-- El asesor cambia su estado (RF-11). Un supervisor puede cambiar el de cualquiera.
CREATE FUNCTION rumbo.cambiar_estado_asesor(p_estado rumbo.estado_asesor, p_asesor_id bigint DEFAULT NULL)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_rol    rumbo.rol_usuario := rumbo._exigir_rol('asesor', 'supervisor', 'admin');
    v_asesor bigint := coalesce(p_asesor_id, rumbo.ctx_asesor_id());
BEGIN
    IF v_rol = 'asesor' AND v_asesor IS DISTINCT FROM rumbo.ctx_asesor_id() THEN
        RAISE EXCEPTION 'Un asesor solo puede cambiar su propio estado' USING ERRCODE = 'insufficient_privilege';
    END IF;
    UPDATE rumbo.asesor SET estado = p_estado WHERE id = v_asesor;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Asesor % no encontrado', v_asesor USING ERRCODE = 'no_data_found';
    END IF;
END $$;

CREATE FUNCTION rumbo.anular_venta(p_venta_id bigint, p_motivo text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    PERFORM rumbo._exigir_rol('supervisor', 'admin');
    UPDATE rumbo.venta SET anulada_en = now(), motivo_anulacion = p_motivo WHERE id = p_venta_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Venta % no encontrada', p_venta_id USING ERRCODE = 'no_data_found';
    END IF;
END $$;

-- ─────────────────────────────── Tareas programadas (Celery beat) ───────────────────────────────

-- RF-14: reasigna los leads cuyo asesor no registró ningún intento dentro del tiempo máximo.
CREATE FUNCTION rumbo.reasignar_sin_primera_llamada()
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
          AND l.asignado_en < now() - make_interval(mins => v_minutos)
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

-- RF-13: al abrir el horario reparte la cola en orden de llegada.
CREATE FUNCTION rumbo.liberar_cola()
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_total integer := 0;
    r       record;
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    IF NOT rumbo.en_horario() THEN
        RETURN 0;
    END IF;
    PERFORM rumbo._bloquear_reparto();

    FOR r IN
        SELECT l.id FROM rumbo.lead l
        WHERE l.estado_asignacion = 'en_cola'
        ORDER BY l.primer_contacto_en, l.id
        FOR UPDATE OF l SKIP LOCKED
    LOOP
        EXIT WHEN rumbo._repartir(r.id, 'cola_horario') IS NULL;   -- nadie en turno: el resto espera
        v_total := v_total + 1;
    END LOOP;
    RETURN v_total;
END $$;

-- ─────────────────────────────── LOPDP: derecho de supresión ───────────────────────────────

-- Anonimiza un lead: conserva las métricas (intentos, ventas, etapas) pero elimina los
-- datos personales del lead y de sus mensajes. Irreversible.
CREATE FUNCTION rumbo.anonimizar_lead(p_lead_id bigint)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    PERFORM rumbo._exigir_rol('admin');
    PERFORM rumbo._bloquear_reparto();
    PERFORM 1 FROM rumbo.lead WHERE id = p_lead_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'El lead % no existe', p_lead_id USING ERRCODE = 'no_data_found';
    END IF;

    UPDATE rumbo.lead
    SET telefono       = '+99' || lpad(p_lead_id::text, 12, '0'),
        nombre_perfil  = NULL,
        datos          = '{}'::jsonb,
        anonimizado_en = now()
    WHERE id = p_lead_id;

    UPDATE rumbo.mensaje_whatsapp
    SET cuerpo = NULL, payload = '{}'::jsonb
    WHERE lead_id = p_lead_id;
END $$;
