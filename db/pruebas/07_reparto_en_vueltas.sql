-- 015 · Reparto en vueltas: 30 minutos para gestionar, recorre a todos los asesores en turno
-- y, al terminar, vuelve al primero. Datos de _comun.sql: asesores 11, 12 y 13 disponibles, horario 24/7.
CREATE FUNCTION prueba.msg_en(p_wamid text, p_tel text, p_cuando timestamptz)
RETURNS TABLE (lead_id bigint, lead_nuevo boolean, mensaje_nuevo boolean, asesor_id bigint)
LANGUAGE sql AS $$
    SELECT * FROM rumbo.registrar_mensaje_entrante(p_wamid, p_tel, 'Cliente', 1::smallint, 'text', 'Hola', '{}'::jsonb, p_cuando)
$$;
CREATE FUNCTION prueba.lead(p_tel text) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER AS $$ SELECT id FROM rumbo.lead WHERE telefono = p_tel $$;
CREATE FUNCTION prueba.dueno(p_tel text) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT a.usuario_id FROM rumbo.lead l JOIN rumbo.asesor a ON a.id = l.asesor_id WHERE l.telefono = p_tel $$;
-- Simula que pasaron p_min minutos desde que el asesor actual recibió el lead.
CREATE FUNCTION prueba.envejecer(p_tel text, p_min integer) RETURNS void
LANGUAGE sql SECURITY DEFINER AS $$
    UPDATE rumbo.lead SET asignado_en = now() - make_interval(mins => p_min),
                          proxima_accion_en = now() - make_interval(mins => p_min)
    WHERE telefono = p_tel $$;
-- Recorrido del lead: usuario de cada asesor, en orden, con su vuelta ("11:1,12:1,...").
CREATE FUNCTION prueba.recorrido(p_tel text) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT string_agg(a.usuario_id || ':' || s.vuelta, ',' ORDER BY s.id)
    FROM rumbo.asignacion s JOIN rumbo.asesor a ON a.id = s.asesor_id
    WHERE s.lead_id = (SELECT id FROM rumbo.lead WHERE telefono = p_tel) $$;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA prueba TO PUBLIC;

SET ROLE rumbo_app;

-- ───────────── Plazo de 30 minutos ─────────────
SELECT prueba.como(1);
SELECT prueba.afirmar((SELECT valor = '30'::jsonb FROM rumbo.configuracion WHERE clave = 'minutos_primera_llamada'),
                      '015 · el plazo para gestionar un lead nuevo es de 30 minutos');

SELECT prueba.como(0);
SELECT * FROM prueba.msg_en('wamid.v1', '+593998000001', now());
SELECT set_config('prueba.primero', prueba.dueno('+593998000001')::text, true);
SELECT prueba.envejecer('+593998000001', 20);
SELECT rumbo.reasignar_sin_primera_llamada();
SELECT prueba.afirmar((SELECT prueba.dueno('+593998000001')::text = current_setting('prueba.primero')),
                      '015 · a los 20 minutos sin gestionar sigue con su asesor');
SELECT prueba.como(prueba.dueno('+593998000001'));
SELECT prueba.afirmar((SELECT vence_en BETWEEN now() + interval '9 minutes' AND now() + interval '11 minutes' AND vuelta = 1
                       FROM rumbo.plazos_gestion() WHERE lead_id = prueba.lead('+593998000001')),
                      '015 · plazos_gestion: le quedan ~10 minutos, vuelta 1');

-- ───────────── Recorre a todos los asesores y vuelve al primero ─────────────
SELECT prueba.como(0);
SELECT prueba.envejecer('+593998000001', 31);
SELECT rumbo.reasignar_sin_primera_llamada();
SELECT set_config('prueba.segundo', prueba.dueno('+593998000001')::text, true);
SELECT prueba.afirmar((SELECT current_setting('prueba.segundo') <> current_setting('prueba.primero')),
                      '015 · a los 30 minutos sin gestionar pasa a otro asesor');

SELECT prueba.envejecer('+593998000001', 31);
SELECT rumbo.reasignar_sin_primera_llamada();
SELECT set_config('prueba.tercero', prueba.dueno('+593998000001')::text, true);
SELECT prueba.afirmar((SELECT current_setting('prueba.tercero') NOT IN (current_setting('prueba.primero'), current_setting('prueba.segundo'))),
                      '015 · el tercer asesor es uno que todavía no lo tuvo (no vuelve al primero antes de tiempo)');

SELECT prueba.envejecer('+593998000001', 31);
SELECT rumbo.reasignar_sin_primera_llamada();
SELECT prueba.afirmar((SELECT prueba.dueno('+593998000001')::text = current_setting('prueba.primero')),
                      '015 · pasó por los 3 asesores: vuelve al primero');
SELECT prueba.afirmar((SELECT prueba.recorrido('+593998000001') =
                              current_setting('prueba.primero') || ':1,' || current_setting('prueba.segundo') || ':1,'
                              || current_setting('prueba.tercero') || ':1,' || current_setting('prueba.primero') || ':2'),
                      '015 · el historial registra el recorrido con su vuelta (1, 1, 1, 2)');

SELECT prueba.envejecer('+593998000001', 31);
SELECT rumbo.reasignar_sin_primera_llamada();
SELECT prueba.afirmar((SELECT prueba.dueno('+593998000001')::text = current_setting('prueba.segundo')),
                      '015 · la vuelta 2 sigue el mismo orden que la 1');

-- ───────────── Solo cuenta a los asesores en turno ─────────────
SELECT prueba.como(0);
SELECT * FROM prueba.msg_en('wamid.v2', '+593998000002', now());
SELECT set_config('prueba.p2', prueba.dueno('+593998000002')::text, true);
-- Uno de los otros dos se va a pausa
SELECT prueba.como(1);
SELECT rumbo.cambiar_estado_asesor('pausa', (SELECT id FROM rumbo.asesor
                                             WHERE usuario_id <> current_setting('prueba.p2')::bigint ORDER BY usuario_id LIMIT 1));
SELECT prueba.como(0);
SELECT prueba.envejecer('+593998000002', 31);
SELECT rumbo.reasignar_sin_primera_llamada();
SELECT set_config('prueba.s2', prueba.dueno('+593998000002')::text, true);
SELECT prueba.envejecer('+593998000002', 31);
SELECT rumbo.reasignar_sin_primera_llamada();
SELECT prueba.afirmar((SELECT prueba.dueno('+593998000002')::text = current_setting('prueba.p2')
                              AND current_setting('prueba.s2') <> current_setting('prueba.p2')),
                      '015 · con un asesor en pausa, recorre a los 2 en turno y vuelve al primero');
SELECT prueba.como(1);
SELECT rumbo.cambiar_estado_asesor('disponible', a.id) FROM rumbo.asesor a WHERE a.estado = 'pausa';

-- ───────────── Gestionado: ya no corre el plazo ─────────────
SELECT prueba.como(0);
SELECT * FROM prueba.msg_en('wamid.v3', '+593998000003', now());
SELECT prueba.como(prueba.dueno('+593998000003'));
SELECT rumbo.registrar_intento(prueba.lead('+593998000003'), NULL, 'interesado');
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.plazos_gestion() WHERE lead_id = prueba.lead('+593998000003')),
                      '015 · al registrar una llamada el lead deja de estar "sin gestionar"');
SELECT prueba.afirmar((SELECT count(*) FILTER (WHERE l.asesor_id IS DISTINCT FROM rumbo.ctx_asesor_id()) = 0
                       FROM rumbo.plazos_gestion() p JOIN rumbo.lead l ON l.id = p.lead_id),
                      '015 · plazos_gestion: el asesor solo ve sus leads (RLS)');

-- ───────────── Reasignación manual: queda en la vuelta actual ─────────────
SELECT prueba.como(2);
SELECT rumbo.reasignar_manual(prueba.lead('+593998000001'), prueba.asesor(13));
SELECT prueba.afirmar((SELECT vuelta = 2 FROM rumbo.asignacion WHERE lead_id = prueba.lead('+593998000001') ORDER BY id DESC LIMIT 1),
                      '015 · la reasignación manual del supervisor queda en la vuelta en curso');

RESET ROLE;
ROLLBACK;
