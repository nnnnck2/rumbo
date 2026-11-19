-- 018 · Tope de intentos, reapertura, mensajes automáticos, conversiones para Meta, inversión y
--       exportaciones. Datos de _comun.sql: asesores 11, 12 y 13, horario 24/7.
CREATE FUNCTION prueba.msg(p_wamid text, p_tel text, p_referral jsonb DEFAULT NULL, p_texto text DEFAULT 'Hola')
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    PERFORM rumbo.registrar_mensaje_entrante(p_wamid, p_tel, 'Cliente ' || right(p_tel, 3), 1::smallint, 'text', p_texto,
                                             '{}'::jsonb, now());
    IF p_referral IS NOT NULL THEN
        PERFORM rumbo.registrar_origen_anuncio(p_wamid, p_referral);
    END IF;
END $$;
CREATE FUNCTION prueba.l(p_tel text) RETURNS rumbo.lead
LANGUAGE sql STABLE SECURITY DEFINER AS $$ SELECT * FROM rumbo.lead WHERE telefono = p_tel $$;
CREATE FUNCTION prueba.dueno(p_tel text) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT a.usuario_id FROM rumbo.lead l JOIN rumbo.asesor a ON a.id = l.asesor_id WHERE l.telefono = p_tel $$;
CREATE FUNCTION prueba.notas(p_tel text) RETURNS SETOF rumbo.nota_lead
LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT n.* FROM rumbo.nota_lead n JOIN rumbo.lead l ON l.id = n.lead_id WHERE l.telefono = p_tel $$;
CREATE FUNCTION prueba.eventos(p_tel text) RETURNS SETOF rumbo.evento_conversion
LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT e.* FROM rumbo.evento_conversion e JOIN rumbo.lead l ON l.id = e.lead_id WHERE l.telefono = p_tel $$;
CREATE FUNCTION prueba.notif() RETURNS SETOF rumbo.notificacion
LANGUAGE sql STABLE SECURITY DEFINER AS $$ SELECT * FROM rumbo.notificacion $$;
-- Registra un intento con el asesor dueño del lead (vuelve al contexto sistema al terminar).
CREATE FUNCTION prueba.intento(p_tel text, p_resultado text, p_venta jsonb DEFAULT NULL) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM prueba.como(prueba.dueno(p_tel));
    PERFORM rumbo.registrar_intento((prueba.l(p_tel)).id, NULL, p_resultado, NULL, NULL, p_venta);
    PERFORM prueba.como(0);
END $$;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA prueba TO PUBLIC;

-- Tope: 3 intentos por asesor, 4 en total
SET ROLE rumbo_owner;
INSERT INTO rumbo.configuracion (clave, valor) VALUES ('max_intentos_por_lead', '4')
ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor;
UPDATE rumbo.configuracion SET valor = '3' WHERE clave = 'max_intentos_por_asesor';
RESET ROLE;

SET ROLE rumbo_app;
SELECT prueba.como(0);

-- ───────────── SCRUM-89 · Tope de intentos por lead ─────────────
SELECT prueba.msg('wamid.t1', '+593999400001');
SELECT set_config('prueba.primero', prueba.dueno('+593999400001')::text, true);
SELECT prueba.intento('+593999400001', 'no_contesta');
SELECT prueba.intento('+593999400001', 'no_contesta');
SELECT prueba.intento('+593999400001', 'no_contesta');
SELECT prueba.afirmar((SELECT prueba.dueno('+593999400001') <> current_setting('prueba.primero')::bigint
                              AND ((prueba.l('+593999400001')).etapa_codigo = 'nuevo')),
                      '018 · con 3 intentos sin contacto el lead pasa a otro asesor (aún no se descarta)');
SELECT prueba.intento('+593999400001', 'no_contesta');
SELECT prueba.afirmar((SELECT (prueba.l('+593999400001')).etapa_codigo = 'descartado'
                          AND (prueba.l('+593999400001')).motivo_descarte_codigo = 'sin_contacto'
                          AND (prueba.l('+593999400001')).estado_asignacion = 'cerrado'),
                      '018 · al llegar al tope total (4) el lead se descarta solo con motivo "sin contacto"');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM prueba.notas('+593999400001') WHERE texto LIKE 'Descartado automáticamente%'),
                      '018 · queda una nota explicando el descarte automático');

-- ───────────── SCRUM-90 · El descartado vuelve a escribir ─────────────
SELECT prueba.msg('wamid.t2', '+593999400001', NULL, 'Hola, sigo interesado');
SELECT prueba.afirmar((SELECT (prueba.l('+593999400001')).etapa_codigo = 'nuevo'
                          AND (prueba.l('+593999400001')).estado_asignacion = 'asignado'
                          AND (prueba.l('+593999400001')).motivo_descarte_codigo IS NULL),
                      '018 · un descartado que vuelve a escribir se reabre como Nuevo y se reparte');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM prueba.notas('+593999400001') WHERE texto LIKE 'Reabierto automáticamente%'),
                      '018 · la reapertura queda anotada en el lead');
SELECT prueba.afirmar((SELECT count(*) >= 1 FROM prueba.notif()
                       WHERE usuario_id = prueba.dueno('+593999400001') AND tipo IN ('lead_nuevo', 'lead_reasignado')
                         AND lead_id = (prueba.l('+593999400001')).id),
                      '018 · el asesor que lo recibe tiene el aviso');
SELECT prueba.intento('+593999400001', 'no_contesta');
SELECT prueba.afirmar((SELECT (prueba.l('+593999400001')).etapa_codigo = 'nuevo'),
                      '018 · tras reabrir, el tope cuenta de cero (un intento más no lo descarta)');

-- ───────────── SCRUM-90 · Cliente con venta que vuelve a escribir ─────────────
SELECT prueba.msg('wamid.v1', '+593999400002', '{"source_id": "AD-018", "ctwa_clid": "CLID-018"}');
SELECT prueba.intento('+593999400002', 'interesado');
SELECT prueba.intento('+593999400002', 'venta_cerrada', '{"tipo_visa": "Turismo", "valor": 350, "moneda": "USD"}');
SELECT set_config('prueba.vendedor', prueba.dueno('+593999400002')::text, true);
SELECT prueba.msg('wamid.v2', '+593999400002', NULL, '¿Cuándo es mi cita?');
SELECT prueba.afirmar((SELECT (prueba.l('+593999400002')).etapa_codigo = 'cerrado'),
                      '018 · un cliente con venta que vuelve a escribir no cambia de etapa');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM prueba.notif()
                       WHERE usuario_id = current_setting('prueba.vendedor')::bigint AND tipo = 'cliente_escribio'
                         AND titulo LIKE '%(cliente con venta)%'),
                      '018 · su asesor recibe el aviso "cliente con venta le escribió"');

-- ───────────── SCRUM-92 · Conversiones para Meta ─────────────
SELECT prueba.afirmar((SELECT count(*) = 1 FROM prueba.eventos('+593999400002') WHERE evento = 'Purchase' AND ctwa_clid = 'CLID-018'),
                      '018 · la venta de un lead que llegó por un anuncio genera el evento Purchase');
SELECT prueba.afirmar((SELECT count(*) = 0 FROM prueba.eventos('+593999400001')),
                      '018 · un lead sin anuncio (sin ctwa_clid) no genera eventos para Meta');
SELECT prueba.afirmar((SELECT valor = 350 AND moneda = 'USD' FROM rumbo.tomar_eventos_conversion(10)
                       WHERE evento = 'Purchase' AND ctwa_clid = 'CLID-018'),
                      '018 · el worker toma el evento con el valor de la venta');
SELECT rumbo.marcar_evento_conversion((SELECT id FROM prueba.eventos('+593999400002')), NULL);
SELECT prueba.afirmar((SELECT estado = 'enviado' FROM prueba.eventos('+593999400002')), '018 · el evento queda enviado');
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.tomar_eventos_conversion(10)), '018 · un evento enviado no se vuelve a tomar');
SELECT prueba.como(11);
SELECT prueba.debe_fallar($$SELECT * FROM rumbo.tomar_eventos_conversion(10)$$, '42501',
                          '018 · solo el sistema toma eventos de conversión');

-- ───────────── SCRUM-88 · Mensaje automático del sistema ─────────────
SELECT prueba.debe_fallar($$SELECT rumbo.registrar_mensaje_automatico((SELECT id FROM rumbo.lead LIMIT 1), 'wamid.x', 'Hola')$$,
                          '42501', '018 · un asesor no registra mensajes automáticos del sistema');
SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT rumbo.registrar_mensaje_automatico((prueba.l('+593999400001')).id, 'wamid.auto1',
                              'Le llamamos y no contestó', 'text', '{"aviso_no_contesta": true}') IS NOT NULL),
                      '018 · el sistema registra el aviso de "no contestó"');
SELECT prueba.afirmar((SELECT payload @> '{"aviso_no_contesta": true, "automatica": true}' FROM rumbo.mensaje_whatsapp
                       WHERE wa_message_id = 'wamid.auto1'),
                      '018 · el mensaje queda marcado como automático y con su motivo');

-- ───────────── SCRUM-91 · Próxima apertura ─────────────
SELECT prueba.afirmar((SELECT rumbo.proxima_apertura() = now()), '018 · con la atención abierta, la próxima apertura es ahora');
SET ROLE rumbo_owner;
UPDATE rumbo.configuracion SET valor = '{"inicio": "09:00", "fin": "18:00", "dias": [1,2,3,4,5], "zona": "UTC"}'
WHERE clave = 'horario';
RESET ROLE;
SET ROLE rumbo_app;
SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT rumbo.proxima_apertura('2026-11-21 20:00+00') = '2026-11-23 09:00+00'),
                      '018 · un sábado a la noche, la próxima apertura es el lunes a las 9:00');
SELECT prueba.afirmar((SELECT rumbo.proxima_apertura('2026-11-19 07:30+00') = '2026-11-19 09:00+00'),
                      '018 · un jueves antes de abrir, abre ese mismo día a las 9:00');

-- ───────────── Configuración nueva ─────────────
SELECT prueba.como(1);
SELECT prueba.debe_fallar($$UPDATE rumbo.configuracion SET valor = '{"activo": true, "texto": "x", "plantilla": "Con Mayúsculas", "idioma": "es", "horas_entre": 24}'
                            WHERE clave = 'aviso_no_contesta'$$, 'RB422', '018 · nombre de plantilla de Meta inválido');
SELECT prueba.debe_fallar($$UPDATE rumbo.configuracion SET valor = '40' WHERE clave = 'max_intentos_por_lead'$$,
                          'RB422', '018 · el tope de intentos por lead va de 1 a 30');
SELECT prueba.debe_fallar($$UPDATE rumbo.configuracion SET valor = '{"llamadas": 20, "citas": -1, "ventas": 1}' WHERE clave = 'metas_diarias'$$,
                          'RB422', '018 · las metas no pueden ser negativas');
UPDATE rumbo.configuracion SET valor = '{"General": "Saludar", "Turismo": "Preguntar fechas del viaje"}' WHERE clave = 'guiones_llamada';
SELECT prueba.afirmar((SELECT valor ->> 'Turismo' = 'Preguntar fechas del viaje' FROM rumbo.configuracion WHERE clave = 'guiones_llamada'),
                      '018 · el admin guarda un guion por tipo de visa');

-- ───────────── SCRUM-99 · Inversión por anuncio ─────────────
SELECT prueba.como(2);
SELECT prueba.debe_fallar($$SELECT rumbo.registrar_inversion_anuncio((SELECT id FROM rumbo.anuncio WHERE clave = 'AD-018'), 100)$$,
                          '42501', '018 · solo el admin registra la inversión de un anuncio');
SELECT prueba.como(1);
SELECT prueba.debe_fallar($$SELECT rumbo.registrar_inversion_anuncio((SELECT id FROM rumbo.anuncio WHERE clave = 'AD-018'), -5)$$,
                          'RB422', '018 · la inversión no puede ser negativa');
SELECT rumbo.registrar_inversion_anuncio((SELECT id FROM rumbo.anuncio WHERE clave = 'AD-018'), 120.50);
SELECT prueba.afirmar((SELECT inversion = 120.50 FROM rumbo.anuncio WHERE clave = 'AD-018'), '018 · inversión guardada');

-- ───────────── SCRUM-93 · Registro de exportaciones ─────────────
SELECT prueba.como(11);
SELECT prueba.debe_fallar($$SELECT rumbo.registrar_exportacion('leads', 10)$$, '42501', '018 · un asesor no exporta');
SELECT prueba.como(2);
SELECT prueba.afirmar((SELECT rumbo.registrar_exportacion('leads', 10, '{"q": "ana"}') IS NOT NULL),
                      '018 · la exportación de la supervisora queda registrada');
SELECT prueba.debe_fallar($$UPDATE rumbo.exportacion SET filas = 0$$, '42501', '018 · el registro de exportaciones no se edita');

RESET ROLE;
ROLLBACK;
