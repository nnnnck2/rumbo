-- 020 · SCRUM-35 · Registro de ingresos y bloqueo temporal tras varios fallos.
SET ROLE rumbo_app;

-- Sin contexto de usuario (como el login antes de autenticar) se puede registrar y consultar el bloqueo.
SELECT set_config('rumbo.usuario_id', '', true);
SELECT auditoria.registrar_acceso('Ana', 'fallido', '10.0.0.1', 'prueba') FROM generate_series(1, 4);
SELECT prueba.afirmar(auditoria.bloqueo_acceso('ana', '10.0.0.1') IS NULL,
                      '020 · 4 fallos todavía no bloquean');
SELECT auditoria.registrar_acceso('ANA ', 'fallido', '10.0.0.2');
SELECT prueba.afirmar(auditoria.bloqueo_acceso('ana', '10.0.0.9') > now() + interval '14 minutes',
                      '020 · 5 fallos bloquean al usuario 15 min (sin importar mayúsculas ni la IP)');
SELECT prueba.afirmar(auditoria.bloqueo_acceso('beto', '10.0.0.9') IS NULL,
                      '020 · el bloqueo es del usuario, no de los demás');

-- Un ingreso correcto reinicia la cuenta del usuario.
SELECT auditoria.registrar_acceso('carla', 'fallido', '10.0.0.3') FROM generate_series(1, 4);
SELECT auditoria.registrar_acceso('carla', 'ingreso', '10.0.0.3');
SELECT auditoria.registrar_acceso('carla', 'fallido', '10.0.0.3');
SELECT prueba.afirmar(auditoria.bloqueo_acceso('carla', '10.0.0.3') IS NULL,
                      '020 · tras un ingreso correcto los fallos anteriores no cuentan');

-- Muchos usuarios distintos desde una misma IP: se bloquea la IP.
SELECT auditoria.registrar_acceso('u' || g, 'fallido', '10.0.0.50') FROM generate_series(1, 30) g;
SELECT prueba.afirmar(auditoria.bloqueo_acceso('nadie', '10.0.0.50') IS NOT NULL,
                      '020 · 30 fallos desde una IP bloquean esa IP');
SELECT prueba.afirmar(auditoria.bloqueo_acceso('nadie', '10.0.0.51') IS NULL,
                      '020 · otra IP no queda bloqueada');

-- El registro es inmutable y la app no lo lee directo.
SELECT prueba.debe_fallar($$SELECT count(*) FROM auditoria.acceso$$, '42501',
                          '020 · la app no lee auditoria.acceso sin pasar por la función de admin');
SELECT prueba.como(11);
SELECT prueba.debe_fallar($$SELECT * FROM auditoria.accesos_recientes()$$, '42501',
                          '020 · un asesor no ve la auditoría de ingresos');
SELECT prueba.como(1);
SELECT prueba.afirmar((SELECT count(*) FROM auditoria.accesos_recientes(1000)) = 41,
                      '020 · el admin ve todos los ingresos registrados');
SELECT prueba.afirmar((SELECT count(*) FROM auditoria.accesos_recientes(1000, 'ingreso')) = 1,
                      '020 · y los puede filtrar por evento');
RESET ROLE;
SET ROLE rumbo_owner;
SELECT prueba.debe_fallar($$UPDATE auditoria.acceso SET evento = 'ingreso'$$, 'RB403',
                          '020 · ni el dueño puede modificar el registro de ingresos');
SELECT prueba.debe_fallar($$DELETE FROM auditoria.acceso$$, 'RB403',
                          '020 · ni borrarlo');
RESET ROLE;

ROLLBACK;
