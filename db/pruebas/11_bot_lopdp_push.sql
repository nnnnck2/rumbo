-- 019 · Bot, especialidades, LOPDP y push. Datos de _comun.sql: asesores 11, 12 y 13, horario 24/7.
CREATE FUNCTION prueba.l(p_tel text) RETURNS rumbo.lead
LANGUAGE sql STABLE SECURITY DEFINER AS $$ SELECT * FROM rumbo.lead WHERE telefono = p_tel $$;
CREATE FUNCTION prueba.dueno(p_tel text) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT a.usuario_id FROM rumbo.lead l JOIN rumbo.asesor a ON a.id = l.asesor_id WHERE l.telefono = p_tel $$;
CREATE FUNCTION prueba.todos_disponibles_sin_turno() RETURNS void
LANGUAGE sql SECURITY DEFINER AS $$ UPDATE rumbo.asesor SET ultimo_lead_en = NULL $$;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA prueba TO PUBLIC;

SET ROLE rumbo_app;

-- ───────────── SCRUM-115 · Datos que guarda el bot ─────────────
SELECT prueba.como(0);
SELECT prueba.mensaje('wamid.b1', '+593999500001');
SELECT prueba.afirmar((SELECT rumbo.guardar_dato_bot((prueba.l('+593999500001')).id, 'tipo_visa', 'Turismo')),
                      '019 · el bot guarda el tipo de visa');
SELECT prueba.afirmar((SELECT (prueba.l('+593999500001')).tipo_visa = 'Turismo'
                          AND (prueba.l('+593999500001')).datos @> '{"respondio_bot": true}'),
                      '019 · queda el tipo de visa y la marca de que respondió al bot');
SELECT prueba.afirmar((SELECT NOT rumbo.guardar_dato_bot((prueba.l('+593999500001')).id, 'tipo_visa', 'Estudiante')),
                      '019 · el bot no pisa un tipo de visa ya escrito');
SELECT prueba.debe_fallar($$SELECT rumbo.guardar_dato_bot((SELECT id FROM rumbo.lead LIMIT 1), 'telefono', 'x')$$,
                          'RB422', '019 · el bot solo guarda los datos permitidos');
SELECT prueba.como(11);
SELECT prueba.debe_fallar($$SELECT rumbo.guardar_dato_bot((SELECT id FROM rumbo.lead LIMIT 1), 'tipo_visa', 'x')$$,
                          '42501', '019 · un asesor no usa la función del bot');

-- ───────────── SCRUM-118 · Reparto por especialidad ─────────────
SELECT prueba.como(1);
SELECT rumbo.guardar_especialidades(prueba.asesor(13), ARRAY['España'], ARRAY['Estudiante']);
SELECT prueba.como(2);
SELECT prueba.debe_fallar($$SELECT rumbo.guardar_especialidades(prueba.asesor(12), ARRAY['Canadá'], NULL)$$,
                          '42501', '019 · solo el admin define especialidades');
-- Un lead que ya tiene país España y vuelve a repartirse: lo recibe el especialista (13) aunque le toque a otro.
SELECT prueba.como(0);
SELECT prueba.todos_disponibles_sin_turno();
SELECT prueba.mensaje('wamid.e1', '+593999500002');
SELECT rumbo.guardar_dato_bot((prueba.l('+593999500002')).id, 'pais_interes', 'España');
SELECT prueba.como(1);
SELECT rumbo.cambiar_etapa((prueba.l('+593999500002')).id, NULL, 'descartado', 'otro');
SELECT prueba.como(0);
SELECT prueba.mensaje('wamid.e2', '+593999500002');           -- vuelve a escribir: se reabre y se reparte
SELECT prueba.afirmar((SELECT prueba.dueno('+593999500002') = 13 OR
                              (SELECT bool_or(s.asesor_id = prueba.asesor(13)) FROM rumbo.asignacion s
                               WHERE s.lead_id = (prueba.l('+593999500002')).id
                                 AND s.vuelta = (SELECT max(vuelta) FROM rumbo.asignacion WHERE lead_id = s.lead_id))),
                      '019 · el especialista en España recibe el lead (si no lo tuvo ya en esta vuelta)');

-- ───────────── SCRUM-120 · LOPDP ─────────────
SELECT prueba.como(2);
SELECT prueba.debe_fallar($$SELECT rumbo.registrar_solicitud_lopdp((SELECT id FROM rumbo.lead LIMIT 1), 'acceso', current_date)$$,
                          '42501', '019 · solo el admin registra solicitudes LOPDP');
SELECT prueba.como(1);
SELECT prueba.debe_fallar($$SELECT rumbo.registrar_solicitud_lopdp((SELECT id FROM rumbo.lead LIMIT 1), 'acceso', current_date + 1)$$,
                          'RB422', '019 · la fecha de recepción no puede ser futura');
SELECT set_config('prueba.sol', rumbo.registrar_solicitud_lopdp((prueba.l('+593999500001')).id, 'eliminacion',
                                                                current_date - 3, 'Pidió borrar sus datos')::text, true);
SELECT prueba.afirmar((SELECT vence_en = current_date + 12 FROM rumbo.solicitud_lopdp WHERE id = current_setting('prueba.sol')::bigint),
                      '019 · plazo de 15 días desde la recepción');
SELECT prueba.debe_fallar($$SELECT rumbo.atender_solicitud_lopdp(current_setting('prueba.sol')::bigint, 'atendida', '')$$,
                          'RB422', '019 · atender exige escribir la respuesta');
SELECT rumbo.atender_solicitud_lopdp(current_setting('prueba.sol')::bigint, 'atendida', 'Datos anonimizados');
SELECT prueba.debe_fallar($$SELECT rumbo.atender_solicitud_lopdp(current_setting('prueba.sol')::bigint, 'rechazada', 'otra vez')$$,
                          'RB422', '019 · una solicitud atendida no se vuelve a atender');

-- ───────────── SCRUM-122 · Push ─────────────
SELECT prueba.como(11);
SELECT rumbo.guardar_suscripcion_push('https://push.example.com/abc', repeat('k', 40), repeat('a', 16), 'Chrome');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.suscripcion_push), '019 · el asesor ve solo su suscripción');
SELECT prueba.como(12);
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.suscripcion_push), '019 · otro asesor no ve suscripciones ajenas');
RESET ROLE;
SET ROLE rumbo_owner;
SELECT rumbo._avisar(11, 'lead_nuevo', 'Cliente nuevo: prueba push', 'Hola', NULL, 'push:1');
RESET ROLE;
SET ROLE rumbo_app;
SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.tomar_notificaciones_push(10)
                       WHERE titulo = 'Cliente nuevo: prueba push' AND jsonb_array_length(suscripciones) = 1),
                      '019 · el worker toma la notificación con la suscripción de su usuario');
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.tomar_notificaciones_push(10) WHERE titulo = 'Cliente nuevo: prueba push'),
                      '019 · una notificación se envía por push una sola vez');
SELECT rumbo.borrar_suscripcion_push('https://push.example.com/abc');
SELECT prueba.como(11);
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.suscripcion_push), '019 · el sistema borra suscripciones dadas de baja');

-- ───────────── Configuración ─────────────
SELECT prueba.como(1);
SELECT prueba.debe_fallar($$UPDATE rumbo.configuracion SET valor = '{"destinatarios": ["no-es-correo"]}' WHERE clave = 'reporte_semanal'$$,
                          'RB422', '019 · correo inválido en el reporte semanal');
SELECT prueba.debe_fallar($$UPDATE rumbo.configuracion SET valor = '{"tipo": "porcentaje", "valor": 150}' WHERE clave = 'comision'$$,
                          'RB422', '019 · la comisión en porcentaje no pasa de 100');
UPDATE rumbo.configuracion SET valor = '{"destinatarios": ["gerencia@multivisa.ec"]}' WHERE clave = 'reporte_semanal';
SELECT prueba.afirmar((SELECT valor -> 'destinatarios' ->> 0 = 'gerencia@multivisa.ec' FROM rumbo.configuracion WHERE clave = 'reporte_semanal'),
                      '019 · destinatarios del reporte guardados');

RESET ROLE;
ROLLBACK;
