-- Seguridad: RLS, permisos por columna, funciones con validación de rol, CALLFLOW
SET ROLE rumbo_app;

-- Sin contexto la base no muestra nada
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.usuario), 'sin contexto: 0 usuarios visibles');
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.configuracion), 'sin contexto: 0 filas de configuración');
SELECT prueba.debe_fallar($$SELECT * FROM rumbo.registrar_mensaje_entrante('w', '+593990000001', 'x', 1::smallint, 'text', 'x', '{}', now())$$,
                          '42501', 'sin contexto no se pueden ejecutar operaciones');

-- El sistema recibe 3 leads → uno para cada asesor
SELECT prueba.como(0);
SELECT * FROM prueba.mensaje('wamid.s1', '+593990000001');
SELECT * FROM prueba.mensaje('wamid.s2', '+593990000002');
SELECT * FROM prueba.mensaje('wamid.s3', '+593990000003');
SELECT prueba.afirmar((SELECT count(DISTINCT asesor_id) = 3 FROM rumbo.lead), 'sistema ve los 3 leads repartidos');

-- Asesor A
SELECT prueba.como(11);
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.lead), 'asesor ve solo su lead');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.mensaje_whatsapp), 'asesor ve solo los mensajes de su lead');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.asesor), 'asesor ve solo su ficha');
SELECT prueba.afirmar((SELECT count(*) = 0 FROM auditoria.registro), 'asesor no ve la auditoría');
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.webhook_evento), 'asesor no ve el webhook');

UPDATE rumbo.lead SET datos = '{"tipo_visa": "estudiante"}' WHERE asesor_id = prueba.asesor(12);
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.lead WHERE tipo_visa = 'estudiante'), 'asesor no puede editar leads ajenos');
UPDATE rumbo.lead SET datos = '{"tipo_visa": "turismo"}';
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.lead WHERE tipo_visa = 'turismo'), 'asesor edita datos de su lead');

SELECT prueba.debe_fallar($$UPDATE rumbo.lead SET asesor_id = 1$$,            '42501', 'asesor no puede reasignarse leads');
SELECT prueba.debe_fallar($$UPDATE rumbo.lead SET etapa_codigo = 'cerrado'$$, '42501', 'etapa solo por función');
SELECT prueba.debe_fallar($$INSERT INTO rumbo.venta (lead_id, asesor_id, tipo_visa, valor, registrada_por_usuario_id) VALUES (1,1,'x',1,11)$$,
                          '42501', 'nadie inserta ventas directamente');
SELECT prueba.debe_fallar($$INSERT INTO rumbo.intento_llamada (lead_id, asesor_id, numero, resultado_codigo, registrado_por_usuario_id) VALUES (1,1,1,'no_contesta',11)$$,
                          '42501', 'nadie inserta intentos directamente');
UPDATE rumbo.configuracion SET valor = '5' WHERE clave = 'max_intentos_por_asesor';   -- RLS: afecta 0 filas
SELECT prueba.afirmar((SELECT valor = '3' FROM rumbo.configuracion WHERE clave = 'max_intentos_por_asesor'),
                      'asesor no cambia la configuración (RLS la deja intacta)');
SELECT prueba.debe_fallar($$SELECT rumbo._repartir(1, 'manual')$$,            '42501', 'funciones internas no ejecutables');
SELECT prueba.debe_fallar($$SELECT rumbo.reasignar_manual(1, 1)$$,             '42501', 'asesor no reasigna (solo supervisor)');

-- El id del lead de B se obtiene como sistema (el asesor A no lo ve)
SELECT prueba.como(0);
SELECT set_config('prueba.lead_b', (SELECT id::text FROM rumbo.lead WHERE asesor_id = prueba.asesor(12)), true);
SELECT prueba.como(11);
SELECT prueba.debe_fallar(format($$SELECT rumbo.registrar_intento(%s, NULL, 'no_contesta')$$, current_setting('prueba.lead_b')),
                          '42501', 'asesor no registra llamadas en leads ajenos');

-- Notas: el autor debe ser el usuario del contexto
SELECT prueba.debe_fallar(format($$INSERT INTO rumbo.nota_lead (lead_id, autor_usuario_id, texto) SELECT id, 12, 'x' FROM rumbo.lead$$),
                          '42501', 'nota con autor suplantado');
INSERT INTO rumbo.nota_lead (lead_id, autor_usuario_id, texto) SELECT id, 11, 'Llamar en la tarde' FROM rumbo.lead;
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.nota_lead), 'asesor agrega nota a su lead');

-- Supervisor ve todo lo operativo pero no la auditoría
SELECT prueba.como(2);
SELECT prueba.afirmar((SELECT count(*) = 3 FROM rumbo.lead), 'supervisor ve todos los leads');
SELECT prueba.afirmar((SELECT count(*) = 0 FROM auditoria.registro), 'supervisor no ve la auditoría');
SELECT prueba.debe_fallar($$INSERT INTO rumbo.usuario (id, nombre, rol) VALUES (50, 'x', 'admin')$$,
                          '42501', 'supervisor no crea usuarios');

-- Admin
SELECT prueba.como(1);
SELECT prueba.afirmar((SELECT count(*) > 0 FROM auditoria.registro), 'admin lee la auditoría');
SELECT prueba.debe_fallar($$INSERT INTO rumbo.usuario (id, nombre, rol) VALUES (51, 'x', 'sistema')$$,
                          '42501', 'ni el admin crea otro usuario sistema');
SELECT prueba.debe_fallar($$INSERT INTO auditoria.registro (tabla, operacion) VALUES ('x', 'INSERT')$$,
                          '42501', 'nadie escribe la auditoría a mano');

-- Usuario desactivado = sin acceso inmediato
RESET ROLE;
SET ROLE rumbo_owner;
UPDATE rumbo.usuario SET activo = false WHERE id = 11;
SET ROLE rumbo_app;
SELECT prueba.como(11);
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.lead), 'usuario desactivado no ve nada');

-- Un id de usuario inexistente tampoco ve nada
SELECT prueba.como(999);
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.lead), 'usuario inexistente no ve nada');

-- CALLFLOW: solo vistas api, sin datos personales
RESET ROLE;
SET ROLE rumbo_callflow;
SELECT prueba.afirmar((SELECT count(*) = 3 FROM api.asesores), 'CALLFLOW lee api.asesores');
SELECT prueba.afirmar((SELECT count(*) = 0 FROM api.ventas), 'CALLFLOW lee api.ventas');
SELECT prueba.debe_fallar($$SELECT * FROM rumbo.lead$$,     '42501', 'CALLFLOW no accede a leads');
SELECT prueba.debe_fallar($$SELECT * FROM rumbo.usuario$$,  '42501', 'CALLFLOW no accede a usuarios');
SELECT prueba.afirmar((SELECT NOT EXISTS (SELECT 1 FROM information_schema.columns
                                          WHERE table_schema = 'api' AND column_name IN ('telefono', 'nombre_perfil', 'cuerpo'))),
                      'las vistas de CALLFLOW no exponen datos personales');

RESET ROLE;
ROLLBACK;
