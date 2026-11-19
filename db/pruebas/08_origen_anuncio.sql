-- 016 · Origen de cada lead: anuncio de Facebook / Instagram (Click-to-WhatsApp).
-- Datos de _comun.sql: asesores 11, 12 y 13 disponibles, horario 24/7.
CREATE FUNCTION prueba.msg_anuncio(p_wamid text, p_tel text, p_referral jsonb)
RETURNS bigint LANGUAGE plpgsql AS $$
BEGIN
    PERFORM rumbo.registrar_mensaje_entrante(p_wamid, p_tel, 'Cliente', 1::smallint, 'text', 'Hola',
                                             jsonb_build_object('mensaje', jsonb_build_object('referral', p_referral)), now());
    RETURN rumbo.registrar_origen_anuncio(p_wamid, p_referral);
END $$;
CREATE FUNCTION prueba.lead(p_tel text) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER AS $$ SELECT id FROM rumbo.lead WHERE telefono = p_tel $$;
CREATE FUNCTION prueba.dueno(p_tel text) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT a.usuario_id FROM rumbo.lead l JOIN rumbo.asesor a ON a.id = l.asesor_id WHERE l.telefono = p_tel $$;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA prueba TO PUBLIC;

SET ROLE rumbo_app;
SELECT prueba.como(0);

SELECT prueba.afirmar((SELECT prueba.msg_anuncio('wamid.ad1', '+593999100001',
          '{"source_id": "AD-USA", "source_type": "ad", "source_url": "https://fb.me/usa", "headline": "Visa americana",
            "body": "Asesoría para tu visa", "media_type": "image", "ctwa_clid": "CLID1"}') IS NOT NULL),
                      '016 · un mensaje desde un anuncio registra el anuncio');
SELECT prueba.afirmar((SELECT titulo = 'Visa americana' AND tipo_origen = 'ad' AND meta_source_id = 'AD-USA'
                              AND enlace = 'https://fb.me/usa' AND tipo_medio = 'image'
                       FROM rumbo.anuncio WHERE clave = 'AD-USA'),
                      '016 · se guardan id, título, enlace y tipo de medio del anuncio');
SELECT prueba.afirmar((SELECT o.ctwa_clid = 'CLID1' FROM rumbo.lead_origen o WHERE o.lead_id = prueba.lead('+593999100001')),
                      '016 · el lead queda con su anuncio de origen y el id del clic');

-- Otro cliente desde el mismo anuncio: un solo anuncio, dos llegadas
SELECT prueba.msg_anuncio('wamid.ad2', '+593999100002', '{"source_id": "AD-USA", "source_type": "ad"}');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.anuncio WHERE clave = 'AD-USA')
                       AND (SELECT count(*) = 2 FROM rumbo.lead_origen o JOIN rumbo.anuncio a ON a.id = o.anuncio_id WHERE a.clave = 'AD-USA'),
                      '016 · varios leads del mismo anuncio comparten el registro del anuncio');
SELECT prueba.afirmar((SELECT titulo = 'Visa americana' FROM rumbo.anuncio WHERE clave = 'AD-USA'),
                      '016 · un mensaje sin título no borra el título ya guardado');

-- Reintento del webhook: no duplica
SELECT rumbo.registrar_origen_anuncio('wamid.ad1', '{"source_id": "AD-USA"}');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.lead_origen WHERE lead_id = prueba.lead('+593999100001')),
                      '016 · registrar dos veces el mismo mensaje no duplica el origen');

-- Sin identificador: no se registra nada
SELECT set_config('prueba.sin_id', coalesce(prueba.msg_anuncio('wamid.ad3', '+593999100003', '{"headline": "Sin id"}')::text, 'nulo'), true);
SELECT prueba.afirmar(current_setting('prueba.sin_id') = 'nulo'
                       AND (SELECT count(*) = 0 FROM rumbo.lead_origen WHERE lead_id = prueba.lead('+593999100003')),
                      '016 · un referral sin id ni enlace se ignora');
SELECT prueba.msg_anuncio('wamid.ad4', '+593999100004', '{"source_url": "https://ig.me/p/1", "source_type": "post"}');
SELECT prueba.afirmar((SELECT tipo_origen = 'post' AND meta_source_id IS NULL FROM rumbo.anuncio WHERE clave = 'https://ig.me/p/1'),
                      '016 · una publicación sin id de anuncio se identifica por su enlace');

-- Permisos y RLS
SELECT prueba.como(1);
SELECT prueba.debe_fallar($$SELECT rumbo.registrar_origen_anuncio('wamid.ad1', '{"source_id": "X"}')$$, '42501',
                          '016 · solo el sistema registra orígenes (ni el admin)');
SELECT prueba.debe_fallar($$INSERT INTO rumbo.anuncio (clave) VALUES ('a mano')$$, '42501',
                          '016 · nadie inserta anuncios a mano');
SELECT prueba.como(prueba.dueno('+593999100001'));
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.lead_origen o JOIN rumbo.lead l ON l.id = o.lead_id
                       WHERE l.asesor_id IS DISTINCT FROM rumbo.ctx_asesor_id())
                       AND (SELECT count(*) >= 1 FROM rumbo.lead_origen WHERE lead_id = prueba.lead('+593999100001')),
                      '016 · el asesor ve el origen de sus leads y no el de los ajenos (RLS)');
SELECT prueba.afirmar((SELECT count(*) >= 2 FROM rumbo.anuncio), '016 · el asesor ve el catálogo de anuncios');
SELECT prueba.como(2);
SELECT prueba.afirmar((SELECT count(*) = 3 FROM rumbo.lead_origen), '016 · la supervisora ve todos los orígenes');
SELECT prueba.debe_fallar($$UPDATE rumbo.lead_origen SET ctwa_clid = 'x'$$, '42501', '016 · el origen no se edita');

RESET ROLE;
ROLLBACK;
