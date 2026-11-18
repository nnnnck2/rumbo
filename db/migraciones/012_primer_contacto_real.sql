-- 012 · RF-03 (SCRUM-22): fecha del primer contacto = hora del mensaje en WhatsApp
-- Antes el lead tomaba now() al procesarse, así que un evento que esperó en la bandeja del
-- webhook (worker caído, reintentos) o que Meta entregó tarde quedaba con una fecha posterior
-- a la real. Eso también alteraba el orden de la cola de fuera de horario (liberar_cola).
-- Ahora: primer_contacto_en = ocurrido_en del mensaje, y si llega uno más antiguo, se corrige.
-- CREATE OR REPLACE conserva los permisos de 009.

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

    INSERT INTO rumbo.lead AS l (telefono, nombre_perfil, numero_whatsapp_id, primer_contacto_en, ultimo_mensaje_en)
    VALUES (p_telefono, nullif(btrim(p_nombre_perfil), ''), p_numero_whatsapp_id,
            coalesce(p_ocurrido_en, now()), p_ocurrido_en)
    ON CONFLICT (telefono) DO UPDATE
        SET ultimo_mensaje_en  = greatest(l.ultimo_mensaje_en, EXCLUDED.ultimo_mensaje_en),
            -- Meta puede entregar fuera de orden: el primer contacto es el mensaje más antiguo.
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
