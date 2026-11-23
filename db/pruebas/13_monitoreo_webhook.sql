-- 021 · SCRUM-41 · Estado del webhook y alertas a los administradores.
SET ROLE rumbo_app;
SELECT prueba.como(0);
SELECT rumbo.recibir_evento_webhook('prueba-monitoreo-1', true, '{}');
SELECT rumbo.recibir_evento_webhook('prueba-monitoreo-2', false, '{}');
SELECT prueba.afirmar((SELECT recibidos_1h = 1 AND firmas_invalidas_1h = 1 AND ultimo_valido_en IS NOT NULL
                       FROM rumbo.estado_webhook()), '021 · cuenta los válidos y las firmas inválidas de la última hora');
SELECT prueba.afirmar((SELECT atascados = 0 FROM rumbo.estado_webhook()),
                      '021 · un evento recién llegado todavía no cuenta como atascado');
SELECT prueba.afirmar((SELECT atascados = 1 FROM rumbo.estado_webhook(-1)),
                      '021 · un evento válido sin procesar pasado el plazo cuenta como atascado');

SELECT prueba.afirmar(rumbo.alertar_admins('webhook_silencio:prueba', 'Sin mensajes', 'Detalle') = 1,
                      '021 · la alerta le llega al administrador activo');
SELECT prueba.afirmar(rumbo.alertar_admins('webhook_silencio:prueba', 'Sin mensajes', 'Detalle') = 0,
                      '021 · la misma alerta no se repite');
SELECT prueba.como(1);
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.notificacion WHERE tipo = 'alerta_sistema'),
                      '021 · el admin la ve en su campana');
SELECT prueba.afirmar((SELECT true FROM rumbo.estado_webhook()), '021 · el admin puede consultar el estado');
SELECT prueba.como(2);
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.notificacion WHERE tipo = 'alerta_sistema'),
                      '021 · el supervisor no recibe alertas técnicas');
SELECT prueba.debe_fallar($$SELECT * FROM rumbo.estado_webhook()$$, '42501', '021 · el supervisor no consulta el webhook');
SELECT prueba.debe_fallar($$SELECT rumbo.alertar_admins('x:y', 'a', 'b')$$, '42501', '021 · solo el sistema crea alertas');
RESET ROLE;
ROLLBACK;
