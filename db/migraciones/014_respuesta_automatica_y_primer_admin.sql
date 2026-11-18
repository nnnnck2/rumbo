-- 014 · Sprint 2
--   · RF-04 (SCRUM-23): registrar la respuesta automática que el sistema envía al primer mensaje.
--     registrar_mensaje_saliente (006) es para asesores: exige su número y su rol. La respuesta
--     automática sale por el número al que escribió el cliente y la registra el usuario sistema.
--   · RF-30 (SCRUM-27): alta del primer administrador sin entrar a la base como dueño. Solo
--     funciona mientras no haya ningún admin activo; después, los usuarios se crean desde la app.
--   · Aviso de privacidad (LOPDP) por defecto, PENDIENTE de validar con el área.

CREATE FUNCTION rumbo.registrar_respuesta_automatica(p_lead_id bigint, p_wa_message_id text, p_cuerpo text)
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
    VALUES (p_lead_id, v_numero, p_wa_message_id, 'saliente', 'text', p_cuerpo,
            'enviado', '{"automatica": true}', now())
    ON CONFLICT ON CONSTRAINT mensaje_wa_id_uk DO NOTHING
    RETURNING id INTO v_id;
    RETURN v_id;
END $$;

CREATE FUNCTION rumbo.crear_primer_admin(p_usuario_id bigint, p_nombre text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    PERFORM pg_advisory_xact_lock(7240002);     -- dos altas simultáneas: solo una gana
    IF EXISTS (SELECT 1 FROM rumbo.usuario u WHERE u.rol = 'admin' AND u.activo) THEN
        RAISE EXCEPTION 'Ya existe un administrador activo: cree los demás usuarios desde la pantalla Usuarios'
            USING ERRCODE = 'RB422';
    END IF;
    INSERT INTO rumbo.usuario AS u (id, nombre, rol) VALUES (p_usuario_id, p_nombre, 'admin')
    ON CONFLICT (id) DO UPDATE SET rol = 'admin', activo = true, nombre = EXCLUDED.nombre;
END $$;

GRANT EXECUTE ON FUNCTION
    rumbo.registrar_respuesta_automatica(bigint, text, text),
    rumbo.crear_primer_admin(bigint, text)
TO rumbo_app;

INSERT INTO rumbo.configuracion (clave, valor, descripcion) VALUES
    ('texto_privacidad',
     '"Al escribirnos, Multivisa tratará tus datos solo para atender tu consulta, conforme a la Ley Orgánica de Protección de Datos Personales. Puedes pedir acceso, rectificación o eliminación de tus datos respondiendo a este chat."',
     'Aviso de privacidad (LOPDP) que acompaña la respuesta automática. PENDIENTE de validar con el área (SCRUM-23).')
ON CONFLICT (clave) DO NOTHING;
