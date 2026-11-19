-- 016 · Origen de cada lead: de qué anuncio de Facebook / Instagram llegó (paso 1 de la
--       categorización por campaña).
--   · Cuando un cliente toca un anuncio "Enviar mensaje por WhatsApp" (Click-to-WhatsApp),
--     Meta adjunta al primer mensaje el objeto `referral` (id del anuncio, título, texto,
--     enlace, tipo de medio y ctwa_clid). Hasta ahora quedaba solo dentro del payload crudo.
--   · rumbo.anuncio: un registro por anuncio visto (se completa solo). El paso 2 le agregará
--     la campaña / categoría que asigna.
--   · rumbo.lead_origen: cada vez que un lead llega o vuelve desde un anuncio (solo inserción).
--   · rumbo.registrar_origen_anuncio(): la llama el worker del webhook (rol sistema).
--   · Se recuperan los anuncios de los mensajes ya guardados.

-- ─────────────────────────────── Tablas ───────────────────────────────

CREATE TABLE rumbo.anuncio (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- id del anuncio en Meta (source_id); si no viene (p. ej. una publicación), el enlace.
    clave            text        NOT NULL UNIQUE CHECK (length(clave) BETWEEN 1 AND 500),
    meta_source_id   text        CHECK (length(meta_source_id) <= 100),
    tipo_origen      text        NOT NULL DEFAULT 'ad' CHECK (tipo_origen IN ('ad', 'post', 'otro')),
    enlace           text        CHECK (length(enlace) <= 2000),
    titulo           text        CHECK (length(titulo) <= 500),
    texto            text        CHECK (length(texto) <= 4000),
    tipo_medio       text        CHECK (length(tipo_medio) <= 30),
    primer_visto_en  timestamptz NOT NULL DEFAULT now(),
    ultimo_visto_en  timestamptz NOT NULL DEFAULT now(),
    creado_en        timestamptz NOT NULL DEFAULT now(),
    actualizado_en   timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE rumbo.anuncio IS 'Anuncios de Meta (Click-to-WhatsApp) de los que llegaron leads. Se crean solos.';

CREATE TABLE rumbo.lead_origen (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lead_id      bigint      NOT NULL REFERENCES rumbo.lead (id),
    anuncio_id   bigint      NOT NULL REFERENCES rumbo.anuncio (id),
    mensaje_id   bigint      NOT NULL UNIQUE REFERENCES rumbo.mensaje_whatsapp (id),
    ctwa_clid    text        CHECK (length(ctwa_clid) <= 500),   -- id del clic, para medir conversiones en Meta
    llegado_en   timestamptz NOT NULL,
    creado_en    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX lead_origen_lead_idx ON rumbo.lead_origen (lead_id, llegado_en);
CREATE INDEX lead_origen_anuncio_idx ON rumbo.lead_origen (anuncio_id);
COMMENT ON TABLE rumbo.lead_origen IS 'Cada llegada de un lead desde un anuncio. El primero es el origen del lead.';

CREATE TRIGGER lead_origen_inmutable BEFORE UPDATE OR DELETE ON rumbo.lead_origen
    FOR EACH ROW EXECUTE FUNCTION rumbo.tg_solo_insercion();
CREATE TRIGGER anuncio_sin_truncate BEFORE TRUNCATE ON rumbo.anuncio
    FOR EACH STATEMENT EXECUTE FUNCTION rumbo.tg_sin_truncate();
CREATE TRIGGER lead_origen_sin_truncate BEFORE TRUNCATE ON rumbo.lead_origen
    FOR EACH STATEMENT EXECUTE FUNCTION rumbo.tg_sin_truncate();

-- ─────────────────────────────── Seguridad ───────────────────────────────

-- Como en 007: RLS para rumbo_app; el dueño no la tiene forzada (funciones SECURITY DEFINER).
ALTER TABLE rumbo.anuncio     ENABLE ROW LEVEL SECURITY;
ALTER TABLE rumbo.lead_origen ENABLE ROW LEVEL SECURITY;

-- Los anuncios son de la empresa (no tienen datos personales): los ve cualquier usuario activo.
CREATE POLICY anuncio_leer ON rumbo.anuncio FOR SELECT TO rumbo_app
    USING ((SELECT rumbo.ctx_rol()) IS NOT NULL);
-- El origen de un lead se ve si el lead se ve (la subconsulta aplica lead_leer).
CREATE POLICY lead_origen_leer ON rumbo.lead_origen FOR SELECT TO rumbo_app
    USING (EXISTS (SELECT 1 FROM rumbo.lead l WHERE l.id = lead_id));

GRANT SELECT ON rumbo.anuncio, rumbo.lead_origen TO rumbo_app;

-- ─────────────────────────────── Registro ───────────────────────────────

-- Guarda el anuncio de origen de un mensaje entrante. Idempotente (un reintento del webhook no
-- duplica nada). Devuelve el id del anuncio, o NULL si el referral no trae con qué identificarlo.
CREATE FUNCTION rumbo.registrar_origen_anuncio(p_wa_message_id text, p_referral jsonb)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_msg     rumbo.mensaje_whatsapp;
    v_clave   text;
    v_tipo    text;
    v_anuncio bigint;
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
            -- Meta puede mandar el título/texto en un mensaje y no en otro: se completa, no se borra.
            titulo  = coalesce(EXCLUDED.titulo, a.titulo),
            texto   = coalesce(EXCLUDED.texto, a.texto),
            enlace  = coalesce(EXCLUDED.enlace, a.enlace),
            tipo_medio = coalesce(EXCLUDED.tipo_medio, a.tipo_medio),
            actualizado_en = now()
    RETURNING a.id INTO v_anuncio;

    INSERT INTO rumbo.lead_origen (lead_id, anuncio_id, mensaje_id, ctwa_clid, llegado_en)
    VALUES (v_msg.lead_id, v_anuncio, v_msg.id, left(nullif(btrim(p_referral ->> 'ctwa_clid'), ''), 500), v_msg.ocurrido_en)
    ON CONFLICT (mensaje_id) DO NOTHING;

    RETURN v_anuncio;
END $$;
GRANT EXECUTE ON FUNCTION rumbo.registrar_origen_anuncio(text, jsonb) TO rumbo_app;

-- ─────────────────────────────── Recuperar lo ya recibido ───────────────────────────────

-- Los mensajes guardados antes de esta migración tienen el referral en su payload crudo.
DO $$
DECLARE r record;
BEGIN
    PERFORM set_config('rumbo.usuario_id', '0', true);   -- usuario sistema (para _exigir_rol)
    FOR r IN
        SELECT m.wa_message_id, m.payload -> 'mensaje' -> 'referral' AS referral
        FROM rumbo.mensaje_whatsapp m
        WHERE m.direccion = 'entrante' AND jsonb_typeof(m.payload -> 'mensaje' -> 'referral') = 'object'
        ORDER BY m.ocurrido_en
    LOOP
        PERFORM rumbo.registrar_origen_anuncio(r.wa_message_id, r.referral);
    END LOOP;
END $$;
