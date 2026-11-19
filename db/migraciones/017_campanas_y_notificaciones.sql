-- 017 · Campañas por país y notificaciones (como CALLFLOW)
--   · Las campañas de Meta se organizan por PAÍS (definido por el área). El admin asigna el país
--     y un nombre de campaña a cada anuncio; los leads que llegan de ese anuncio quedan con ese
--     país de interés (y también los que ya habían llegado sin país).
--   · rumbo.notificacion: avisos para cada usuario. Los genera la base en cada evento:
--       asesor     → cliente nuevo, cliente reasignado a usted, cliente que pasó a otro asesor,
--                    cliente que volvió a escribir, quedan 10 min para gestionar, hora de llamar;
--       supervisor → llamada atrasada, cliente que pasó por todos los asesores sin ser gestionado;
--       admin      → anuncio nuevo sin país.
--   · rumbo.generar_avisos(): avisos por tiempo (lo llama Celery cada minuto, rol sistema).

-- ─────────────────────────────── Campañas por país ───────────────────────────────

ALTER TABLE rumbo.anuncio
    ADD COLUMN pais            text CHECK (length(btrim(pais)) BETWEEN 1 AND 80),
    ADD COLUMN nombre_campana  text CHECK (length(btrim(nombre_campana)) BETWEEN 1 AND 120),
    ADD COLUMN categorizado_en timestamptz,
    ADD COLUMN categorizado_por_usuario_id bigint REFERENCES rumbo.usuario (id);
COMMENT ON COLUMN rumbo.anuncio.pais IS 'País de la campaña: los leads que llegan de este anuncio toman este país de interés.';

-- Pone el país de la campaña a un lead que todavía no tiene país de interés (no pisa lo que el asesor escribió).
CREATE FUNCTION rumbo._aplicar_pais_campana(p_lead_id bigint, p_pais text, p_campana text)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    UPDATE rumbo.lead
    SET datos = datos || jsonb_build_object('pais_interes', p_pais)
                      || CASE WHEN p_campana IS NULL THEN '{}'::jsonb ELSE jsonb_build_object('campana', p_campana) END
    WHERE id = p_lead_id AND coalesce(btrim(datos ->> 'pais_interes'), '') = '';
    RETURN FOUND;
END $$;

-- El admin asigna el país (y un nombre) a la campaña del anuncio. Devuelve cuántos leads tomaron el país.
CREATE FUNCTION rumbo.categorizar_anuncio(p_anuncio_id bigint, p_pais text, p_nombre_campana text DEFAULT NULL)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_pais    text := nullif(btrim(p_pais), '');
    v_nombre  text := nullif(btrim(p_nombre_campana), '');
    v_total   integer := 0;
    r         record;
BEGIN
    PERFORM rumbo._exigir_rol('admin');
    IF v_pais IS NULL THEN
        RAISE EXCEPTION 'Indique el país de la campaña' USING ERRCODE = 'RB422';
    END IF;
    UPDATE rumbo.anuncio
    SET pais = v_pais, nombre_campana = v_nombre, categorizado_en = now(),
        categorizado_por_usuario_id = rumbo.ctx_usuario_id(), actualizado_en = now()
    WHERE id = p_anuncio_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'El anuncio % no existe', p_anuncio_id USING ERRCODE = 'no_data_found';
    END IF;
    -- Leads cuyo PRIMER anuncio es este (el origen del lead) y que aún no tienen país.
    FOR r IN
        SELECT DISTINCT ON (o.lead_id) o.lead_id, o.anuncio_id
        FROM rumbo.lead_origen o
        WHERE o.lead_id IN (SELECT lead_id FROM rumbo.lead_origen WHERE anuncio_id = p_anuncio_id)
        ORDER BY o.lead_id, o.llegado_en, o.id
    LOOP
        IF r.anuncio_id = p_anuncio_id AND rumbo._aplicar_pais_campana(r.lead_id, v_pais, v_nombre) THEN
            v_total := v_total + 1;
        END IF;
    END LOOP;
    -- El aviso de "anuncio sin país" ya no hace falta.
    UPDATE rumbo.notificacion SET leida_en = now()
    WHERE tipo = 'anuncio_sin_pais' AND clave = 'anuncio:' || p_anuncio_id AND leida_en IS NULL;
    RETURN v_total;
END $$;

-- ─────────────────────────────── Notificaciones ───────────────────────────────

CREATE TABLE rumbo.notificacion (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id  bigint      NOT NULL REFERENCES rumbo.usuario (id),
    tipo        text        NOT NULL CHECK (tipo IN ('lead_nuevo', 'lead_reasignado', 'lead_quitado', 'cliente_escribio',
                                                     'plazo_por_vencer', 'hora_de_llamar', 'llamada_atrasada',
                                                     'sin_gestionar_vuelta', 'anuncio_sin_pais')),
    titulo      text        NOT NULL CHECK (length(titulo) BETWEEN 1 AND 200),
    mensaje     text        CHECK (length(mensaje) <= 1000),
    lead_id     bigint      REFERENCES rumbo.lead (id),
    url         text        CHECK (url IS NULL OR (url LIKE '/%' AND url NOT LIKE '//%' AND length(url) <= 300)),
    clave       text        CHECK (length(clave) <= 200),   -- evita repetir el mismo aviso
    leida_en    timestamptz,
    creado_en   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT notificacion_clave_uk UNIQUE (usuario_id, clave)
);
CREATE INDEX notificacion_usuario_idx ON rumbo.notificacion (usuario_id, id DESC);
CREATE INDEX notificacion_sin_leer_idx ON rumbo.notificacion (usuario_id) WHERE leida_en IS NULL;
CREATE TRIGGER notificacion_sin_truncate BEFORE TRUNCATE ON rumbo.notificacion
    FOR EACH STATEMENT EXECUTE FUNCTION rumbo.tg_sin_truncate();

ALTER TABLE rumbo.notificacion ENABLE ROW LEVEL SECURITY;
-- Cada usuario ve y marca como leídas solo las suyas.
CREATE POLICY notificacion_leer ON rumbo.notificacion FOR SELECT TO rumbo_app
    USING (usuario_id = (SELECT rumbo.ctx_usuario_id()));
CREATE POLICY notificacion_marcar ON rumbo.notificacion FOR UPDATE TO rumbo_app
    USING (usuario_id = (SELECT rumbo.ctx_usuario_id()))
    WITH CHECK (usuario_id = (SELECT rumbo.ctx_usuario_id()));
GRANT SELECT, UPDATE (leida_en) ON rumbo.notificacion TO rumbo_app;

-- Crea un aviso (interno). Con clave repetida no hace nada.
CREATE FUNCTION rumbo._avisar(p_usuario_id bigint, p_tipo text, p_titulo text, p_mensaje text,
                              p_lead_id bigint DEFAULT NULL, p_clave text DEFAULT NULL, p_url text DEFAULT NULL)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    IF p_usuario_id IS NULL THEN
        RETURN;
    END IF;
    INSERT INTO rumbo.notificacion (usuario_id, tipo, titulo, mensaje, lead_id, url, clave)
    VALUES (p_usuario_id, p_tipo, left(p_titulo, 200), left(p_mensaje, 1000), p_lead_id,
            coalesce(p_url, CASE WHEN p_lead_id IS NOT NULL THEN '/leads/' || p_lead_id || '/' END), p_clave)
    ON CONFLICT ON CONSTRAINT notificacion_clave_uk DO NOTHING;
END $$;

-- Avisa a todos los supervisores y administradores activos (o solo a los admin).
CREATE FUNCTION rumbo._avisar_supervision(p_tipo text, p_titulo text, p_mensaje text, p_lead_id bigint,
                                          p_clave text, p_solo_admin boolean DEFAULT false)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE u record;
BEGIN
    FOR u IN SELECT id FROM rumbo.usuario
             WHERE activo AND (rol = 'admin' OR (rol = 'supervisor' AND NOT p_solo_admin)) LOOP
        PERFORM rumbo._avisar(u.id, p_tipo, p_titulo, p_mensaje, p_lead_id, p_clave);
    END LOOP;
END $$;

CREATE FUNCTION rumbo._nombre_lead(p_lead_id bigint) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
    SELECT coalesce(nullif(btrim(nombre_perfil), ''), telefono) FROM rumbo.lead WHERE id = p_lead_id
$$;

-- Al asignar un lead: avisa al asesor que lo recibe, al que lo pierde y, si ya pasó por todos, a supervisión.
CREATE FUNCTION rumbo.tg_avisar_asignacion() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_nombre   text := rumbo._nombre_lead(NEW.lead_id);
    v_nuevo    bigint := (SELECT usuario_id FROM rumbo.asesor WHERE id = NEW.asesor_id);
    v_anterior bigint := (SELECT usuario_id FROM rumbo.asesor WHERE id = NEW.asesor_anterior_id);
    v_minutos  integer := rumbo.config_int('minutos_primera_llamada', 30);
    v_por      text := CASE NEW.motivo
                           WHEN 'sin_primera_llamada' THEN 'no fue gestionado a tiempo por el asesor anterior'
                           WHEN 'reintentos_agotados' THEN 'el asesor anterior no logró contactarlo'
                           WHEN 'manual'              THEN 'se lo asignó el supervisor'
                           WHEN 'asesor_inactivo'     THEN 'su asesor anterior ya no está activo'
                           ELSE 'llegó un cliente nuevo' END;
BEGIN
    IF NEW.motivo IN ('reparto', 'cola_horario') AND NEW.asesor_anterior_id IS NULL THEN
        PERFORM rumbo._avisar(v_nuevo, 'lead_nuevo', 'Cliente nuevo: ' || v_nombre,
                              'Tiene ' || v_minutos || ' minutos para llamarlo y registrar la llamada.',
                              NEW.lead_id, 'asignacion:' || NEW.id);
    ELSE
        PERFORM rumbo._avisar(v_nuevo, 'lead_reasignado', 'Le asignaron a ' || v_nombre,
                              'Lo recibe porque ' || v_por || '. Tiene ' || v_minutos || ' minutos para gestionarlo.',
                              NEW.lead_id, 'asignacion:' || NEW.id);
    END IF;
    IF v_anterior IS NOT NULL AND v_anterior <> v_nuevo THEN
        PERFORM rumbo._avisar(v_anterior, 'lead_quitado', v_nombre || ' pasó a otro asesor',
                              CASE NEW.motivo
                                  WHEN 'sin_primera_llamada' THEN 'No se registró ninguna llamada en ' || v_minutos || ' minutos.'
                                  WHEN 'reintentos_agotados' THEN 'Se agotaron los intentos sin contacto.'
                                  WHEN 'manual'              THEN 'El supervisor lo reasignó.'
                                  ELSE NULL END,
                              NULL, 'quitado:' || NEW.id);
    END IF;
    -- Empezó una vuelta nueva: pasó por todos los asesores en turno y nadie lo gestionó.
    IF NEW.vuelta > 1 AND NOT EXISTS (SELECT 1 FROM rumbo.asignacion s
                                      WHERE s.lead_id = NEW.lead_id AND s.vuelta = NEW.vuelta AND s.id <> NEW.id) THEN
        PERFORM rumbo._avisar_supervision('sin_gestionar_vuelta', v_nombre || ': nadie lo gestionó',
                                          'Pasó por todos los asesores en turno. Empieza la vuelta ' || NEW.vuelta || '.',
                                          NEW.lead_id, 'vuelta:' || NEW.lead_id || ':' || NEW.vuelta);
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER asignacion_avisar AFTER INSERT ON rumbo.asignacion
    FOR EACH ROW EXECUTE FUNCTION rumbo.tg_avisar_asignacion();

-- El cliente vuelve a escribir: aviso a su asesor (como mucho uno cada 10 minutos por cliente).
CREATE FUNCTION rumbo.tg_avisar_mensaje() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_lead rumbo.lead;
BEGIN
    IF NEW.direccion <> 'entrante' THEN
        RETURN NULL;
    END IF;
    SELECT * INTO v_lead FROM rumbo.lead WHERE id = NEW.lead_id;
    IF v_lead.estado_asignacion = 'asignado' AND v_lead.asesor_id IS NOT NULL THEN
        PERFORM rumbo._avisar((SELECT usuario_id FROM rumbo.asesor WHERE id = v_lead.asesor_id), 'cliente_escribio',
                              rumbo._nombre_lead(NEW.lead_id) || ' le escribió por WhatsApp',
                              coalesce(left(NEW.cuerpo, 140), '[' || NEW.tipo || ']'), NEW.lead_id,
                              'escribio:' || NEW.lead_id || ':' || floor(extract(epoch FROM NEW.ocurrido_en) / 600)::bigint);
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER mensaje_avisar AFTER INSERT ON rumbo.mensaje_whatsapp
    FOR EACH ROW EXECUTE FUNCTION rumbo.tg_avisar_mensaje();

-- Anuncio nuevo: avisa a los administradores para que le pongan el país.
CREATE FUNCTION rumbo.tg_avisar_anuncio() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE u record;
BEGIN
    FOR u IN SELECT id FROM rumbo.usuario WHERE activo AND rol = 'admin' LOOP
        PERFORM rumbo._avisar(u.id, 'anuncio_sin_pais', 'Anuncio nuevo sin país',
                              coalesce(NEW.titulo, NEW.clave) || ' · Asígnele el país de la campaña.', NULL,
                              'anuncio:' || NEW.id, '/leads/campanas/#anuncio-' || NEW.id);
    END LOOP;
    RETURN NULL;
END $$;
CREATE TRIGGER anuncio_avisar AFTER INSERT ON rumbo.anuncio
    FOR EACH ROW EXECUTE FUNCTION rumbo.tg_avisar_anuncio();

-- El origen de un lead aplica el país de la campaña si el anuncio ya tiene país (reemplaza a 016).
CREATE OR REPLACE FUNCTION rumbo.registrar_origen_anuncio(p_wa_message_id text, p_referral jsonb)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_msg     rumbo.mensaje_whatsapp;
    v_clave   text;
    v_tipo    text;
    v_anuncio rumbo.anuncio;
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    IF p_referral IS NULL OR jsonb_typeof(p_referral) <> 'object' THEN
        RETURN NULL;
    END IF;
    SELECT * INTO v_msg FROM rumbo.mensaje_whatsapp WHERE wa_message_id = p_wa_message_id AND direccion = 'entrante';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Mensaje % no registrado', p_wa_message_id USING ERRCODE = 'no_data_found';
    END IF;

    v_clave := left(coalesce(nullif(btrim(p_referral ->> 'source_id'), ''), nullif(btrim(p_referral ->> 'source_url'), '')), 500);
    IF v_clave IS NULL THEN
        RETURN NULL;
    END IF;
    v_tipo := CASE lower(p_referral ->> 'source_type') WHEN 'ad' THEN 'ad' WHEN 'post' THEN 'post' ELSE 'otro' END;

    INSERT INTO rumbo.anuncio AS a (clave, meta_source_id, tipo_origen, enlace, titulo, texto, tipo_medio,
                                    primer_visto_en, ultimo_visto_en)
    VALUES (v_clave,
            left(nullif(btrim(p_referral ->> 'source_id'), ''), 100),
            v_tipo,
            left(nullif(btrim(p_referral ->> 'source_url'), ''), 2000),
            left(nullif(btrim(p_referral ->> 'headline'), ''), 500),
            left(nullif(btrim(p_referral ->> 'body'), ''), 4000),
            left(nullif(btrim(p_referral ->> 'media_type'), ''), 30),
            v_msg.ocurrido_en, v_msg.ocurrido_en)
    ON CONFLICT (clave) DO UPDATE
        SET primer_visto_en = least(a.primer_visto_en, EXCLUDED.primer_visto_en),
            ultimo_visto_en = greatest(a.ultimo_visto_en, EXCLUDED.ultimo_visto_en),
            titulo  = coalesce(EXCLUDED.titulo, a.titulo),
            texto   = coalesce(EXCLUDED.texto, a.texto),
            enlace  = coalesce(EXCLUDED.enlace, a.enlace),
            tipo_medio = coalesce(EXCLUDED.tipo_medio, a.tipo_medio),
            actualizado_en = now()
    RETURNING a.* INTO v_anuncio;

    INSERT INTO rumbo.lead_origen (lead_id, anuncio_id, mensaje_id, ctwa_clid, llegado_en)
    VALUES (v_msg.lead_id, v_anuncio.id, v_msg.id, left(nullif(btrim(p_referral ->> 'ctwa_clid'), ''), 500), v_msg.ocurrido_en)
    ON CONFLICT (mensaje_id) DO NOTHING;

    -- Solo si este anuncio es el ORIGEN del lead (su primera llegada) y la campaña ya tiene país.
    IF v_anuncio.pais IS NOT NULL AND v_anuncio.id = (SELECT o.anuncio_id FROM rumbo.lead_origen o
                                                      WHERE o.lead_id = v_msg.lead_id ORDER BY o.llegado_en, o.id LIMIT 1) THEN
        PERFORM rumbo._aplicar_pais_campana(v_msg.lead_id, v_anuncio.pais, v_anuncio.nombre_campana);
    END IF;
    RETURN v_anuncio.id;
END $$;

-- Avisos por tiempo. Celery la llama cada minuto (rol sistema). Solo dentro del turno.
CREATE FUNCTION rumbo.generar_avisos()
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_antes integer := (SELECT count(*) FROM rumbo.notificacion);
    r       record;
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    IF NOT rumbo.en_horario() THEN
        RETURN 0;
    END IF;

    -- Asesor: quedan 10 minutos o menos para gestionar un cliente.
    FOR r IN
        SELECT p.lead_id, p.vence_en, a.usuario_id, l.asignado_en
        FROM rumbo.plazos_gestion() p
        JOIN rumbo.lead l ON l.id = p.lead_id
        JOIN rumbo.asesor a ON a.id = l.asesor_id
        WHERE p.vence_en > now() AND p.vence_en <= now() + interval '10 minutes'
    LOOP
        PERFORM rumbo._avisar(r.usuario_id, 'plazo_por_vencer',
                              'Quedan ' || greatest(1, ceil(extract(epoch FROM r.vence_en - now()) / 60))::int || ' min para ' || rumbo._nombre_lead(r.lead_id),
                              'Si no registra una llamada, pasa a otro asesor.', r.lead_id,
                              'vence:' || r.lead_id || ':' || floor(extract(epoch FROM r.asignado_en))::bigint);
    END LOOP;

    -- Asesor: llegó la hora de una llamada agendada o de un reintento (ya gestionado antes).
    FOR r IN
        SELECT l.id AS lead_id, l.proxima_accion_en, a.usuario_id
        FROM rumbo.lead l
        JOIN rumbo.asesor a ON a.id = l.asesor_id
        WHERE l.estado_asignacion = 'asignado'
          AND l.proxima_accion_en BETWEEN now() - interval '5 minutes' AND now()
          AND EXISTS (SELECT 1 FROM rumbo.intento_llamada i WHERE i.lead_id = l.id AND i.asesor_id = l.asesor_id)
    LOOP
        PERFORM rumbo._avisar(r.usuario_id, 'hora_de_llamar', 'Es hora de llamar a ' || rumbo._nombre_lead(r.lead_id),
                              'Llamada programada para las ' || to_char(r.proxima_accion_en AT TIME ZONE
                                  coalesce((SELECT valor ->> 'zona' FROM rumbo.configuracion WHERE clave = 'horario'), 'UTC'), 'HH24:MI') || '.',
                              r.lead_id, 'hora:' || r.lead_id || ':' || floor(extract(epoch FROM r.proxima_accion_en))::bigint);
    END LOOP;

    -- Supervisión: llamadas atrasadas más del umbral (las mismas de la pantalla "Llamadas atrasadas").
    FOR r IN SELECT * FROM rumbo.leads_sin_llamar() LOOP
        PERFORM rumbo._avisar_supervision('llamada_atrasada', 'Llamada atrasada: ' || coalesce(r.nombre_perfil, r.telefono),
                                          coalesce(r.asesor, 'Sin asesor') || ' · ' || r.minutos || ' min de espera',
                                          r.lead_id, 'atraso:' || r.lead_id || ':' || floor(extract(epoch FROM r.desde))::bigint);
    END LOOP;

    RETURN (SELECT count(*) FROM rumbo.notificacion) - v_antes;
END $$;

-- La app marca como leídas las propias (RLS); esta función es para "marcar todas" en una sola orden.
CREATE FUNCTION rumbo.marcar_notificaciones_leidas(p_ids bigint[] DEFAULT NULL)
RETURNS integer
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, rumbo AS $$
DECLARE v integer;
BEGIN
    UPDATE rumbo.notificacion SET leida_en = now()
    WHERE leida_en IS NULL AND usuario_id = rumbo.ctx_usuario_id() AND (p_ids IS NULL OR id = ANY (p_ids));
    GET DIAGNOSTICS v = ROW_COUNT;
    RETURN v;
END $$;

GRANT EXECUTE ON FUNCTION rumbo.categorizar_anuncio(bigint, text, text), rumbo.generar_avisos(),
                          rumbo.marcar_notificaciones_leidas(bigint[]) TO rumbo_app;
