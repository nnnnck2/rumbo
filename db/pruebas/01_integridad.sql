-- Integridad transaccional y restricciones (como dueño: aquí se prueba la base, no los permisos)
SET ROLE rumbo_owner;
SELECT prueba.como(1);

SELECT prueba.debe_fallar($$INSERT INTO rumbo.lead (telefono) VALUES ('0991234567')$$,
                          '23514', 'teléfono sin formato E.164');

INSERT INTO rumbo.lead (telefono) VALUES ('+593991000001');
SELECT prueba.debe_fallar($$INSERT INTO rumbo.lead (telefono) VALUES ('+593991000001')$$,
                          '23505', 'teléfono duplicado');

SELECT prueba.debe_fallar($$INSERT INTO rumbo.lead (telefono, datos) VALUES ('+593991000002', '{"tipo_visa": 5}')$$,
                          '23514', 'jsonb: tipo_visa debe ser texto');
SELECT prueba.debe_fallar($$INSERT INTO rumbo.lead (telefono, datos) VALUES ('+593991000002', '[1,2]')$$,
                          '23514', 'jsonb: datos debe ser un objeto');

INSERT INTO rumbo.lead (telefono, datos) VALUES ('+593991000003', '{"tipo_visa": "turismo", "pais_interes": "EE.UU.", "campania": "black_friday"}');
SELECT prueba.afirmar((SELECT tipo_visa = 'turismo' AND pais_interes = 'EE.UU.' FROM rumbo.lead WHERE telefono = '+593991000003'),
                      'modelado híbrido: columnas generadas desde jsonb');

-- Bloqueo optimista: la versión la incrementa la base, no la app
UPDATE rumbo.lead SET nombre_perfil = 'Ana', version = 999 WHERE telefono = '+593991000001';
SELECT prueba.afirmar((SELECT version = 2 FROM rumbo.lead WHERE telefono = '+593991000001'),
                      'versión incrementada por trigger e ignorado el valor manual');

-- Máquina de estados
SELECT prueba.debe_fallar($$UPDATE rumbo.lead SET etapa_codigo = 'descartado' WHERE telefono = '+593991000001'$$,
                          '23514', 'descartar sin motivo');
UPDATE rumbo.lead SET etapa_codigo = 'cerrado' WHERE telefono = '+593991000001';
SELECT prueba.afirmar((SELECT estado_asignacion = 'cerrado' AND cerrado_en IS NOT NULL FROM rumbo.lead WHERE telefono = '+593991000001'),
                      'etapa final cierra el lead');
SELECT prueba.debe_fallar($$UPDATE rumbo.lead SET etapa_codigo = 'en_contacto' WHERE telefono = '+593991000001'$$,
                          'RB422', 'transición no permitida cerrado → en_contacto');
SELECT prueba.afirmar((SELECT count(*) = 2 FROM rumbo.lead_etapa_historial h
                       JOIN rumbo.lead l ON l.id = h.lead_id WHERE l.telefono = '+593991000001'),
                      'historial de etapas registrado');

-- Solo inserción / sin borrado
SELECT prueba.debe_fallar($$DELETE FROM rumbo.lead WHERE telefono = '+593991000003'$$, 'RB403', 'borrar un lead');
SELECT prueba.debe_fallar($$TRUNCATE rumbo.lead CASCADE$$, 'RB403', 'TRUNCATE de leads');
SELECT prueba.debe_fallar($$DELETE FROM rumbo.lead_etapa_historial$$, 'RB403', 'borrar historial de etapas');

-- Ventas inmutables
INSERT INTO rumbo.venta (lead_id, asesor_id, tipo_visa, valor, registrada_por_usuario_id)
SELECT l.id, prueba.asesor(11), 'turismo', 850, 1 FROM rumbo.lead l WHERE l.telefono = '+593991000003';
SELECT prueba.debe_fallar($$INSERT INTO rumbo.venta (lead_id, asesor_id, tipo_visa, valor, registrada_por_usuario_id)
                            SELECT id, 1, 'turismo', 0, 1 FROM rumbo.lead LIMIT 1$$, '23514', 'venta con valor 0');
SELECT prueba.debe_fallar($$UPDATE rumbo.venta SET valor = 1$$, 'RB403', 'modificar el valor de una venta');
SELECT prueba.debe_fallar($$UPDATE rumbo.venta SET anulada_en = now()$$, '23514', 'anular sin motivo');
UPDATE rumbo.venta SET anulada_en = now(), motivo_anulacion = 'Cliente desistió';
SELECT prueba.debe_fallar($$UPDATE rumbo.venta SET anulada_en = now(), motivo_anulacion = 'otra vez'$$, 'RB403', 'anular dos veces');

-- Configuración jsonb validada
SELECT prueba.debe_fallar($$UPDATE rumbo.configuracion SET valor = '{"inicio":"18:00","fin":"09:00","dias":[1],"zona":"UTC"}' WHERE clave = 'horario'$$,
                          'RB422', 'horario con inicio > fin');
SELECT prueba.debe_fallar($$UPDATE rumbo.configuracion SET valor = '{"inicio":"09:00","fin":"18:00","dias":[1],"zona":"Marte/Olimpo"}' WHERE clave = 'horario'$$,
                          'RB422', 'zona horaria inexistente');
SELECT prueba.debe_fallar($$UPDATE rumbo.configuracion SET valor = '50' WHERE clave = 'max_intentos_por_asesor'$$,
                          'RB422', 'máximo de intentos fuera de rango');
SELECT prueba.debe_fallar($$INSERT INTO rumbo.configuracion (clave, valor) VALUES ('clave_rara', '1')$$,
                          'RB422', 'clave de configuración desconocida');

-- Un usuario supervisor no puede ser asesor
SELECT prueba.debe_fallar($$INSERT INTO rumbo.asesor (usuario_id) VALUES (2)$$, 'RB422', 'asesor con usuario sin rol asesor');

-- Auditoría
SELECT prueba.afirmar((SELECT count(*) > 0 FROM auditoria.registro WHERE tabla = 'rumbo.lead' AND operacion = 'UPDATE'),
                      'cambios de lead auditados');
SELECT prueba.afirmar((SELECT bool_and(despues ->> 'telefono' LIKE 'sha256:%') FROM auditoria.registro
                       WHERE tabla = 'rumbo.lead' AND operacion = 'INSERT'),
                      'auditoría guarda el teléfono como hash, no en claro');
SELECT prueba.afirmar((SELECT bool_and(usuario_id = 1) FROM auditoria.registro WHERE tabla = 'rumbo.venta'),
                      'auditoría registra el usuario de la app');
SELECT prueba.afirmar((SELECT cambios ? 'nombre_perfil' AND NOT cambios ? 'version'
                       FROM auditoria.registro WHERE tabla = 'rumbo.lead' AND operacion = 'UPDATE' ORDER BY id LIMIT 1),
                      'auditoría guarda solo las columnas que cambiaron');
SELECT prueba.debe_fallar($$UPDATE auditoria.registro SET usuario_id = 99$$, 'RB403', 'modificar la auditoría');
SELECT prueba.debe_fallar($$DELETE FROM auditoria.registro$$,              'RB403', 'borrar la auditoría');

RESET ROLE;
ROLLBACK;
