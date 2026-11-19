-- 017 · Campañas por país y notificaciones. Datos de _comun.sql: asesores 11, 12 y 13, horario 24/7.
CREATE FUNCTION prueba.msg(p_wamid text, p_tel text, p_referral jsonb DEFAULT NULL, p_texto text DEFAULT 'Hola')
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM rumbo.registrar_mensaje_entrante(p_wamid, p_tel, 'Cliente ' || right(p_tel, 3), 1::smallint, 'text', p_texto,
                                             '{}'::jsonb, now());
    IF p_referral IS NOT NULL THEN
        PERFORM rumbo.registrar_origen_anuncio(p_wamid, p_referral);
    END IF;
END $$;
CREATE FUNCTION prueba.lead(p_tel text) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER AS $$ SELECT id FROM rumbo.lead WHERE telefono = p_tel $$;
CREATE FUNCTION prueba.pais(p_tel text) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER AS $$ SELECT pais_interes FROM rumbo.lead WHERE telefono = p_tel $$;
CREATE FUNCTION prueba.dueno(p_tel text) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT a.usuario_id FROM rumbo.lead l JOIN rumbo.asesor a ON a.id = l.asesor_id WHERE l.telefono = p_tel $$;
CREATE FUNCTION prueba.avisos(p_usuario bigint, p_tipo text) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER AS $$ SELECT count(*) FROM rumbo.notificacion WHERE usuario_id = p_usuario AND tipo = p_tipo $$;
CREATE FUNCTION prueba.envejecer(p_tel text, p_min integer) RETURNS void
LANGUAGE sql SECURITY DEFINER AS $$
    UPDATE rumbo.lead SET asignado_en = now() - make_interval(mins => p_min),
                          proxima_accion_en = now() - make_interval(mins => p_min)
    WHERE telefono = p_tel $$;
CREATE FUNCTION prueba.notif() RETURNS SETOF rumbo.notificacion
LANGUAGE sql STABLE SECURITY DEFINER AS $$ SELECT * FROM rumbo.notificacion $$;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA prueba TO PUBLIC;

SET ROLE rumbo_app;
SELECT prueba.como(0);

-- ───────────── Campañas por país ─────────────
SELECT prueba.msg('wamid.c1', '+593999200001', '{"source_id": "AD-ESP", "headline": "Visa España"}');
SELECT prueba.afirmar((SELECT prueba.pais('+593999200001') IS NULL), '017 · anuncio sin país: el lead llega sin país');
SELECT prueba.afirmar((SELECT prueba.avisos(1, 'anuncio_sin_pais') = 1),
                      '017 · al admin le llega el aviso "anuncio nuevo sin país"');
SELECT prueba.afirmar((SELECT prueba.avisos(2, 'anuncio_sin_pais') = 0), '017 · la supervisora no recibe ese aviso');

SELECT prueba.como(2);
SELECT prueba.debe_fallar($$SELECT rumbo.categorizar_anuncio((SELECT id FROM rumbo.anuncio WHERE clave = 'AD-ESP'), 'España')$$,
                          '42501', '017 · solo el admin asigna el país de una campaña');
SELECT prueba.como(1);
SELECT prueba.debe_fallar($$SELECT rumbo.categorizar_anuncio((SELECT id FROM rumbo.anuncio WHERE clave = 'AD-ESP'), '  ')$$,
                          'RB422', '017 · el país es obligatorio');
SELECT prueba.afirmar((SELECT rumbo.categorizar_anuncio((SELECT id FROM rumbo.anuncio WHERE clave = 'AD-ESP'), 'España', 'España nov') = 1),
                      '017 · al asignar el país, los leads que ya llegaron de ese anuncio lo toman');
SELECT prueba.afirmar((SELECT prueba.pais('+593999200001') = 'España'), '017 · el lead quedó con país de interés España');
SELECT prueba.afirmar((SELECT count(*) = 0 FROM prueba.notif() WHERE tipo = 'anuncio_sin_pais' AND leida_en IS NULL),
                      '017 · el aviso de anuncio sin país se da por leído al categorizarlo');

SELECT prueba.como(0);
SELECT prueba.msg('wamid.c2', '+593999200002', '{"source_id": "AD-ESP"}');
SELECT prueba.afirmar((SELECT prueba.pais('+593999200002') = 'España'),
                      '017 · un lead nuevo de un anuncio con país queda con ese país al llegar');

-- No pisa lo que el asesor escribió
SELECT prueba.msg('wamid.c3', '+593999200003');
SELECT prueba.como(prueba.dueno('+593999200003'));
UPDATE rumbo.lead SET datos = datos || '{"pais_interes": "Canadá"}' WHERE telefono = '+593999200003';
SELECT prueba.como(0);
SELECT prueba.msg('wamid.c3b', '+593999200003', '{"source_id": "AD-ESP"}');
SELECT prueba.afirmar((SELECT prueba.pais('+593999200003') = 'Canadá'),
                      '017 · si el lead ya tenía país (lo escribió el asesor), la campaña no lo cambia');

-- ───────────── Notificaciones al asesor ─────────────
SELECT prueba.msg('wamid.n1', '+593999300001', NULL, 'Hola');
SELECT set_config('prueba.d1', prueba.dueno('+593999300001')::text, true);
SELECT prueba.afirmar((SELECT prueba.avisos(current_setting('prueba.d1')::bigint, 'lead_nuevo') >= 1),
                      '017 · al asesor le llega "Cliente nuevo"');
SELECT prueba.msg('wamid.n2', '+593999300001', NULL, 'Sigo esperando su llamada');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM prueba.notif()
                       WHERE usuario_id = current_setting('prueba.d1')::bigint AND tipo = 'cliente_escribio'
                         AND mensaje = 'Sigo esperando su llamada'),
                      '017 · si el cliente vuelve a escribir, su asesor recibe el aviso con el mensaje');
SELECT prueba.msg('wamid.n3', '+593999300001', NULL, 'Hola??');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM prueba.notif()
                       WHERE usuario_id = current_setting('prueba.d1')::bigint AND tipo = 'cliente_escribio'),
                      '017 · varios mensajes seguidos: un solo aviso cada 10 minutos');

-- Quedan 10 minutos
SELECT prueba.envejecer('+593999300001', 22);
SELECT rumbo.generar_avisos();
SELECT rumbo.generar_avisos();
SELECT prueba.afirmar((SELECT prueba.avisos(current_setting('prueba.d1')::bigint, 'plazo_por_vencer') = 1),
                      '017 · a los 22 min: "quedan 8 min" (una sola vez aunque se revise varias veces)');

-- Pasa a otro asesor: aviso al que lo pierde y al que lo recibe
SELECT prueba.envejecer('+593999300001', 31);
SELECT rumbo.reasignar_sin_primera_llamada();
SELECT set_config('prueba.d2', prueba.dueno('+593999300001')::text, true);
SELECT prueba.afirmar((SELECT prueba.avisos(current_setting('prueba.d1')::bigint, 'lead_quitado') = 1),
                      '017 · el asesor que no lo gestionó recibe "pasó a otro asesor"');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM prueba.notif() WHERE usuario_id = current_setting('prueba.d2')::bigint
                         AND tipo = 'lead_reasignado' AND mensaje LIKE '%no fue gestionado a tiempo%'),
                      '017 · el nuevo asesor recibe "le asignaron" con el motivo');

-- Pasa por todos: aviso a supervisión
SELECT prueba.envejecer('+593999300001', 31);
SELECT rumbo.reasignar_sin_primera_llamada();
SELECT prueba.envejecer('+593999300001', 31);
SELECT rumbo.reasignar_sin_primera_llamada();
SELECT prueba.afirmar((SELECT prueba.avisos(2, 'sin_gestionar_vuelta') = 1 AND prueba.avisos(1, 'sin_gestionar_vuelta') = 1),
                      '017 · cuando pasó por todos sin ser gestionado, avisa a supervisora y admin');

-- Hora de llamar (reintento ya gestionado)
SELECT prueba.msg('wamid.h1', '+593999400001');
SELECT prueba.como(prueba.dueno('+593999400001'));
SELECT rumbo.registrar_intento(prueba.lead('+593999400001'), NULL, 'no_contesta');
SELECT prueba.como(0);
RESET ROLE; SET ROLE rumbo_owner;
UPDATE rumbo.lead SET proxima_accion_en = now() - interval '1 minute' WHERE telefono = '+593999400001';
SET ROLE rumbo_app;
SELECT rumbo.generar_avisos();
SELECT prueba.afirmar((SELECT prueba.avisos(prueba.dueno('+593999400001'), 'hora_de_llamar') = 1),
                      '017 · llegó la hora del reintento: "Es hora de llamar"');

-- Supervisión: llamada atrasada
RESET ROLE; SET ROLE rumbo_owner;
UPDATE rumbo.lead SET proxima_accion_en = now() - interval '45 minutes' WHERE telefono = '+593999400001';
SET ROLE rumbo_app;
SELECT rumbo.generar_avisos();
SELECT prueba.afirmar((SELECT prueba.avisos(2, 'llamada_atrasada') >= 1), '017 · la supervisora recibe "Llamada atrasada"');

-- ───────────── Privacidad y lectura ─────────────
SELECT prueba.como(current_setting('prueba.d1')::bigint);
SELECT prueba.afirmar((SELECT count(*) > 0 FROM rumbo.notificacion)
                       AND (SELECT bool_and(usuario_id = rumbo.ctx_usuario_id()) FROM rumbo.notificacion),
                      '017 · cada usuario ve solo sus notificaciones (RLS)');
SELECT prueba.afirmar((SELECT rumbo.marcar_notificaciones_leidas() > 0)
                       , '017 · "marcar todas como leídas"');
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.notificacion WHERE leida_en IS NULL), '017 · ya no quedan sin leer');
SELECT prueba.debe_fallar($$UPDATE rumbo.notificacion SET titulo = 'x'$$, '42501', '017 · solo se puede marcar como leída');
SELECT prueba.debe_fallar($$INSERT INTO rumbo.notificacion (usuario_id, tipo, titulo) VALUES (1, 'lead_nuevo', 'x')$$,
                          '42501', '017 · nadie crea notificaciones a mano');
SELECT prueba.debe_fallar($$SELECT rumbo.generar_avisos()$$, '42501', '017 · solo el sistema genera los avisos por tiempo');

RESET ROLE;
ROLLBACK;
