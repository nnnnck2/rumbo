-- 025 · SCRUM-43 · LOPDP: registro del consentimiento del titular
--   · rumbo.registrar_consentimiento(): el asesor (dueño del lead), el supervisor o el admin dejan constancia de que
--     el cliente aceptó el tratamiento de sus datos, con el medio (llamada, WhatsApp, presencial, formulario).
--     Guarda la fecha en lead.consentimiento_en y la evidencia en lead.datos.consentimiento (quién y por qué medio).
--     Queda además en la auditoría (005). La primera constancia no se pisa: si ya había, devuelve false.
--   · rumbo.registrar_lead_manual() acepta p_consentimiento: el asesor marca que el cliente aceptó al registrarlo.
--   · rumbo.aviso_privacidad_enviado(): cuándo se le envió el aviso de privacidad (respuesta automática), para la ficha.

CREATE FUNCTION rumbo.registrar_consentimiento(p_lead_id bigint, p_medio text)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_rol  rumbo.rol_usuario := rumbo._exigir_rol('asesor', 'supervisor', 'admin');
    v_lead rumbo.lead := rumbo._tomar_lead(p_lead_id, NULL, v_rol);
BEGIN
    IF p_medio NOT IN ('llamada', 'whatsapp', 'presencial', 'formulario') THEN
        RAISE EXCEPTION 'Medio de consentimiento inválido: %', p_medio USING ERRCODE = 'RB422';
    END IF;
    IF v_lead.anonimizado_en IS NOT NULL THEN
        RAISE EXCEPTION 'El lead % fue anonimizado', p_lead_id USING ERRCODE = 'RB422';
    END IF;
    IF v_lead.consentimiento_en IS NOT NULL THEN
        RETURN false;
    END IF;
    UPDATE rumbo.lead
    SET consentimiento_en = now(),
        datos = datos || jsonb_build_object('consentimiento',
                    jsonb_build_object('medio', p_medio, 'usuario_id', rumbo.ctx_usuario_id(), 'en', now()))
    WHERE id = p_lead_id;
    RETURN true;
END $$;

CREATE FUNCTION rumbo.aviso_privacidad_enviado(p_lead_id bigint) RETURNS timestamptz
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog, rumbo AS $$
    -- La respuesta automática lleva el aviso al final (texto_privacidad). RLS: solo si puede ver el lead.
    SELECT min(m.ocurrido_en) FROM rumbo.mensaje_whatsapp m
    WHERE m.lead_id = p_lead_id AND m.direccion = 'saliente' AND m.payload @> '{"automatica": true}'
      AND m.cuerpo LIKE '%' || (SELECT c.valor #>> '{}' FROM rumbo.configuracion c WHERE c.clave = 'texto_privacidad') || '%'
$$;

-- registrar_lead_manual con consentimiento (misma lógica que 023).
DROP FUNCTION rumbo.registrar_lead_manual(text, text, text, text, text, text);
CREATE FUNCTION rumbo.registrar_lead_manual(p_telefono text, p_nombre text, p_origen text,
                                            p_tipo_visa text DEFAULT NULL, p_pais text DEFAULT NULL,
                                            p_nota text DEFAULT NULL, p_consentimiento boolean DEFAULT false)
RETURNS TABLE (r_lead_id bigint, r_nuevo boolean, r_asesor_id bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_rol     rumbo.rol_usuario := rumbo._exigir_rol('asesor', 'supervisor', 'admin');
    v_usuario bigint := rumbo.ctx_usuario_id();
    v_asesor  bigint := rumbo.ctx_asesor_id();
    v_lead    bigint;
    v_asignar boolean;
    v_medio   text;
BEGIN
    IF p_origen NOT IN ('llamada', 'referido', 'visita', 'otro') THEN
        RAISE EXCEPTION 'Canal de origen inválido: %', p_origen USING ERRCODE = 'RB422';
    END IF;
    IF p_telefono IS NULL OR p_telefono !~ '^\+[1-9][0-9]{7,14}$' THEN
        RAISE EXCEPTION 'Teléfono inválido: use el formato internacional (+593…)' USING ERRCODE = 'RB422';
    END IF;
    PERFORM rumbo._bloquear_reparto();

    SELECT l.id INTO v_lead FROM rumbo.lead l WHERE l.telefono = p_telefono;
    IF FOUND THEN
        RETURN QUERY SELECT v_lead, false, (SELECT l.asesor_id FROM rumbo.lead l WHERE l.id = v_lead);
        RETURN;
    END IF;

    v_medio := CASE p_origen WHEN 'visita' THEN 'presencial' ELSE 'llamada' END;
    INSERT INTO rumbo.lead (telefono, nombre_perfil, origen, datos, primer_contacto_en, consentimiento_en)
    VALUES (p_telefono, nullif(left(btrim(coalesce(p_nombre, '')), 200), ''), p_origen,
            jsonb_strip_nulls(jsonb_build_object(
                'tipo_visa', nullif(btrim(coalesce(p_tipo_visa, '')), ''),
                'pais_interes', nullif(btrim(coalesce(p_pais, '')), ''),
                'registrado_por', v_usuario,
                'consentimiento', CASE WHEN p_consentimiento THEN
                    jsonb_build_object('medio', v_medio, 'usuario_id', v_usuario, 'en', now()) END)),
            now(), CASE WHEN p_consentimiento THEN now() END)
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

GRANT EXECUTE ON FUNCTION rumbo.registrar_consentimiento(bigint, text), rumbo.aviso_privacidad_enviado(bigint),
                          rumbo.registrar_lead_manual(text, text, text, text, text, text, boolean) TO rumbo_app;
