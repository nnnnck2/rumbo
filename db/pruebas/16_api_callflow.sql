-- 024 · SCRUM-57 · Funciones que usa la API HTTPS de CALLFLOW.
SET ROLE rumbo_owner;
INSERT INTO rumbo.lead (telefono) VALUES ('+593997700001'), ('+593997700002');
INSERT INTO rumbo.venta (lead_id, asesor_id, tipo_visa, valor, registrada_por_usuario_id)
SELECT l.id, prueba.asesor(11), 'Turismo', 100 + row_number() OVER (), 11 FROM rumbo.lead l WHERE l.telefono LIKE '+59399770000%';
RESET ROLE;
SET ROLE rumbo_app;

SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT count(*) = 2 FROM api.callflow_ventas()), '024 · trae todas las ventas la primera vez');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM api.callflow_ventas(NULL, NULL, 1)), '024 · respeta el límite');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM api.callflow_ventas(
                           (SELECT actualizado_en FROM api.callflow_ventas(NULL, NULL, 1)),
                           (SELECT venta_id FROM api.callflow_ventas(NULL, NULL, 1)))),
                      '024 · paginado: después de la primera queda la segunda');
SELECT prueba.afirmar((SELECT asesor_codigo_callflow = 'EMP-011' FROM api.callflow_ventas() LIMIT 1),
                      '024 · cada venta trae el código CALLFLOW del asesor');
SELECT prueba.afirmar((SELECT count(*) = 3 FROM api.callflow_asesores()), '024 · lista los asesores');
SELECT prueba.afirmar(NOT EXISTS (SELECT 1 FROM information_schema.columns
                                  WHERE table_schema = 'api' AND table_name = 'ventas'
                                    AND column_name IN ('telefono', 'nombre_perfil', 'lead_id')),
                      '024 · sin datos personales del cliente');

SELECT prueba.como(1);
SELECT prueba.debe_fallar($$SELECT * FROM api.callflow_ventas()$$, '42501', '024 · ni el admin la usa desde la app (solo el sistema)');
SELECT prueba.como(11);
SELECT prueba.debe_fallar($$SELECT * FROM api.callflow_asesores()$$, '42501', '024 · un asesor no consulta la API');
SELECT prueba.debe_fallar($$SELECT * FROM api.ventas$$, '42501', '024 · la app no lee la vista directo');
RESET ROLE;
ROLLBACK;
