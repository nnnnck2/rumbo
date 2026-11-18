-- Sprint 2 · criterios de SCRUM-23 (RF-04), SCRUM-25 (RF-11) y SCRUM-27 (RF-30)
-- Datos de _comun.sql: admin 1, supervisora 2, asesores 11, 12 (número 1) y 13 (número 2), todos disponibles.

SET ROLE rumbo_app;

-- ───────────── RF-04 · Respuesta automática (SCRUM-23) ─────────────
SELECT prueba.como(0);
SELECT * FROM prueba.mensaje('wamid.auto1', '+593994000001');
SELECT prueba.afirmar((SELECT rumbo.registrar_respuesta_automatica(
                           (SELECT id FROM rumbo.lead WHERE telefono = '+593994000001'), 'wamid.resp1', 'Hola') IS NOT NULL),
                      'RF-04 · el sistema registra la respuesta automática');
SELECT prueba.afirmar((SELECT direccion = 'saliente' AND numero_whatsapp_id = 1 AND enviado_por_asesor_id IS NULL
                              AND payload ? 'automatica'
                       FROM rumbo.mensaje_whatsapp WHERE wa_message_id = 'wamid.resp1'),
                      'RF-04 · sale por el número al que escribió el cliente, sin asesor, marcada como automática');
SELECT prueba.afirmar((SELECT rumbo.registrar_respuesta_automatica(
                           (SELECT id FROM rumbo.lead WHERE telefono = '+593994000001'), 'wamid.resp1', 'Hola') IS NULL),
                      'RF-04 · registrar el mismo envío dos veces no lo duplica');
SELECT prueba.afirmar((SELECT valor #>> '{}' LIKE '%Protección de Datos Personales%'
                       FROM rumbo.configuracion WHERE clave = 'texto_privacidad'),
                      'RF-04 · hay un aviso de privacidad (LOPDP) configurado');

SELECT prueba.como(11);
SELECT prueba.debe_fallar($$SELECT rumbo.registrar_respuesta_automatica(1, 'wamid.x', 'x')$$, '42501',
                          'RF-04 · un asesor no puede registrar respuestas automáticas');

-- Los textos se editan desde la configuración (admin)
SELECT prueba.como(1);
UPDATE rumbo.configuracion SET valor = '"Aviso validado por el área."' WHERE clave = 'texto_privacidad';
SELECT prueba.afirmar((SELECT valor #>> '{}' = 'Aviso validado por el área.' FROM rumbo.configuracion
                       WHERE clave = 'texto_privacidad'),
                      'RF-04 · el admin edita el aviso de privacidad');

-- ───────────── RF-11 · Estado del asesor (SCRUM-25) ─────────────
SELECT prueba.como(11);
SELECT rumbo.cambiar_estado_asesor('pausa');
SELECT prueba.afirmar((SELECT estado = 'pausa' AND estado_desde >= now() FROM rumbo.asesor WHERE id = prueba.asesor(11)),
                      'RF-11 · el asesor cambia su propio estado (y se registra desde cuándo)');
SELECT prueba.debe_fallar(format('SELECT rumbo.cambiar_estado_asesor(%L, %s)', 'pausa', prueba.asesor(12)), '42501',
                          'RF-11 · un asesor no puede cambiar el estado de otro');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.asesor),
                      'RF-11 · un asesor solo ve su propia ficha de asesor');

SELECT prueba.como(2);
SELECT prueba.afirmar((SELECT count(*) = 3 FROM rumbo.asesor),
                      'RF-11 · el supervisor ve el estado de todos los asesores');
SELECT rumbo.cambiar_estado_asesor('fuera_turno', prueba.asesor(12));
SELECT prueba.afirmar((SELECT estado = 'fuera_turno' FROM rumbo.asesor WHERE id = prueba.asesor(12)),
                      'RF-11 · el supervisor cambia el estado de otro asesor');

-- Solo los disponibles reciben: A en pausa, B fuera de turno → todo va a C
SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT bool_and(asesor_id = prueba.asesor(13)) FROM (
                           SELECT * FROM prueba.mensaje('wamid.e1', '+593994000011') UNION ALL
                           SELECT * FROM prueba.mensaje('wamid.e2', '+593994000012')) t),
                      'RF-11 · en pausa y fuera de turno no reciben leads: solo el disponible');

SELECT prueba.como(13);
SELECT rumbo.cambiar_estado_asesor('fuera_turno');
SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT asesor_id IS NULL FROM prueba.mensaje('wamid.e3', '+593994000013')),
                      'RF-11 · si nadie está disponible el lead queda en cola');

-- ───────────── RF-30 · Roles (SCRUM-27) ─────────────
SELECT prueba.como(11);
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.lead WHERE asesor_id IS DISTINCT FROM prueba.asesor(11)),
                      'RF-30 · el asesor solo ve sus leads');
SELECT prueba.debe_fallar($$INSERT INTO rumbo.usuario (id, nombre, rol) VALUES (50, 'X', 'asesor')$$, '42501',
                          'RF-30 · un asesor no crea usuarios');
SELECT prueba.como(2);
SELECT prueba.afirmar((SELECT count(*) >= 4 FROM rumbo.lead), 'RF-30 · el supervisor ve todos los leads');
SELECT prueba.debe_fallar($$INSERT INTO rumbo.usuario (id, nombre, rol) VALUES (50, 'X', 'asesor')$$, '42501',
                          'RF-30 · el supervisor no crea usuarios');
UPDATE rumbo.configuracion SET valor = '5' WHERE clave = 'max_intentos_por_asesor';
SELECT prueba.afirmar((SELECT valor = '3' FROM rumbo.configuracion WHERE clave = 'max_intentos_por_asesor'),
                      'RF-30 · el supervisor no cambia la configuración');

SELECT prueba.como(1);
INSERT INTO rumbo.usuario (id, nombre, rol) VALUES (50, 'Nueva Asesora', 'asesor');
INSERT INTO rumbo.asesor (usuario_id, numero_whatsapp_id, codigo_callflow) VALUES (50, 1, 'EMP-050');
SELECT prueba.afirmar((SELECT estado = 'fuera_turno' FROM rumbo.asesor WHERE usuario_id = 50),
                      'RF-30 · el admin crea un asesor (empieza fuera de turno)');
SELECT prueba.debe_fallar($$UPDATE rumbo.usuario SET rol = 'supervisor' WHERE id = 50$$, 'RB422',
                          'RF-30 · un asesor no cambia de rol');
UPDATE rumbo.usuario SET activo = false WHERE id = 50;
SELECT prueba.como(50);
SELECT prueba.afirmar((SELECT rumbo.ctx_rol() IS NULL), 'RF-30 · un usuario desactivado no tiene rol (no ve nada)');

-- Primer administrador: solo mientras no haya ninguno activo
SELECT prueba.como(0);
SELECT prueba.debe_fallar($$SELECT rumbo.crear_primer_admin(60, 'Otro admin')$$, 'RB422',
                          'RF-30 · con un admin activo no se puede crear otro "primer admin"');
SELECT prueba.como(11);
SELECT prueba.debe_fallar($$SELECT rumbo.crear_primer_admin(60, 'Otro admin')$$, '42501',
                          'RF-30 · solo el sistema llama a crear_primer_admin');
RESET ROLE; SET ROLE rumbo_owner;
UPDATE rumbo.usuario SET activo = false WHERE id = 1;
SET ROLE rumbo_app;
SELECT prueba.como(0);
SELECT rumbo.crear_primer_admin(60, 'Primer admin');
SELECT prueba.afirmar((SELECT rol = 'admin' AND activo FROM rumbo.usuario WHERE id = 60),
                      'RF-30 · sin admins activos, el sistema da de alta al primer administrador');

RESET ROLE;
ROLLBACK;
