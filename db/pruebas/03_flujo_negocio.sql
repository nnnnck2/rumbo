-- Flujo de negocio: reparto, idempotencia, reintentos, bloqueo optimista, ventas, cola
SET ROLE rumbo_app;
SELECT prueba.como(0);

-- Round robin: 6 leads → 2 por asesor
SELECT (prueba.mensaje('wamid.f' || i, '+59399100000' || i)).* FROM generate_series(1, 6) i;
SELECT prueba.afirmar((SELECT array_agg(n ORDER BY n) = '{2,2,2}' FROM (SELECT count(*) n FROM rumbo.lead GROUP BY asesor_id) x),
                      'round robin: 2 leads por asesor');

-- Idempotencia: Meta reenvía el mismo mensaje
SELECT prueba.afirmar((SELECT NOT lead_nuevo AND NOT mensaje_nuevo FROM prueba.mensaje('wamid.f1', '+593991000001')),
                      'mensaje repetido no duplica lead ni mensaje');
SELECT prueba.afirmar((SELECT count(*) = 6 FROM rumbo.mensaje_whatsapp), '6 mensajes guardados');

-- RF-12: el cliente vuelve a escribir → mismo asesor
SELECT set_config('prueba.asesor_l1', (SELECT asesor_id::text FROM rumbo.lead WHERE telefono = '+593991000001'), true);
SELECT prueba.afirmar((SELECT asesor_id::text = current_setting('prueba.asesor_l1')
                       FROM prueba.mensaje('wamid.f1b', '+593991000001')),
                      'cliente que vuelve a escribir conserva su asesor');

-- Reintentos (RF-23): 3 "no contesta" → pasa al siguiente asesor
SELECT set_config('prueba.lead', (SELECT id::text FROM rumbo.lead WHERE telefono = '+593991000001'), true);
SELECT set_config('prueba.usuario_asesor',
                  (SELECT a.usuario_id::text FROM rumbo.asesor a WHERE a.id = current_setting('prueba.asesor_l1')::bigint), true);
SELECT prueba.como(current_setting('prueba.usuario_asesor')::bigint);

SELECT prueba.debe_fallar(format($$SELECT rumbo.registrar_intento(%s, 999, 'no_contesta')$$, current_setting('prueba.lead')),
                          'RB409', 'bloqueo optimista: versión vieja rechazada');
SELECT prueba.debe_fallar(format($$SELECT rumbo.registrar_intento(%s, NULL, 'llamar_despues')$$, current_setting('prueba.lead')),
                          'RB422', 'llamar después exige fecha');
SELECT prueba.debe_fallar(format($$SELECT rumbo.registrar_intento(%s, NULL, 'venta_cerrada')$$, current_setting('prueba.lead')),
                          'RB422', 'venta cerrada exige datos de la venta');

SELECT rumbo.registrar_intento(current_setting('prueba.lead')::bigint, NULL, 'no_contesta');
SELECT rumbo.registrar_intento(current_setting('prueba.lead')::bigint, NULL, 'no_contesta');
SELECT prueba.afirmar((SELECT intentos_asesor_actual = 2 FROM rumbo.lead WHERE id = current_setting('prueba.lead')::bigint),
                      'dos intentos contados');
SELECT rumbo.registrar_intento(current_setting('prueba.lead')::bigint, NULL, 'no_contesta');

SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT asesor_id::text <> current_setting('prueba.asesor_l1')
                              AND intentos_asesor_actual = 0
                              AND estado_asignacion = 'asignado'
                       FROM rumbo.lead WHERE id = current_setting('prueba.lead')::bigint),
                      'al 3er intento el lead pasa a otro asesor y no se cierra');
SELECT prueba.afirmar((SELECT motivo = 'reintentos_agotados' FROM rumbo.asignacion
                       WHERE lead_id = current_setting('prueba.lead')::bigint ORDER BY id DESC LIMIT 1),
                      'reasignación registrada con su motivo');
SELECT prueba.afirmar((SELECT count(*) = 3 FROM rumbo.intento_llamada WHERE lead_id = current_setting('prueba.lead')::bigint),
                      'historial de intentos conservado');

-- El nuevo asesor registra interés y luego la venta
SELECT set_config('prueba.usuario_asesor',
                  (SELECT a.usuario_id::text FROM rumbo.lead l JOIN rumbo.asesor a ON a.id = l.asesor_id
                   WHERE l.id = current_setting('prueba.lead')::bigint), true);
SELECT prueba.como(current_setting('prueba.usuario_asesor')::bigint);
SELECT rumbo.registrar_intento(current_setting('prueba.lead')::bigint, NULL, 'interesado', 'Quiere visa de turismo');
SELECT prueba.afirmar((SELECT etapa_codigo = 'en_asesoria' FROM rumbo.lead WHERE id = current_setting('prueba.lead')::bigint),
                      'interesado avanza a en_asesoria');
SELECT rumbo.registrar_intento(current_setting('prueba.lead')::bigint, NULL, 'venta_cerrada', NULL, NULL,
                               '{"tipo_visa": "turismo", "pais": "EE.UU.", "valor": 1250.50}');
SELECT prueba.afirmar((SELECT etapa_codigo = 'cerrado' AND estado_asignacion = 'cerrado' FROM rumbo.lead WHERE id = current_setting('prueba.lead')::bigint),
                      'venta cierra el lead');
SELECT prueba.afirmar((SELECT valor = 1250.50 FROM rumbo.venta WHERE lead_id = current_setting('prueba.lead')::bigint),
                      'venta registrada con su valor');
SELECT prueba.debe_fallar(format($$SELECT rumbo.registrar_intento(%s, NULL, 'no_contesta')$$, current_setting('prueba.lead')),
                          'RB422', 'no se registran llamadas en un lead cerrado');

RESET ROLE;
SET ROLE rumbo_callflow;
SELECT prueba.afirmar((SELECT count(*) = 1 AND min(asesor_codigo_callflow) LIKE 'EMP-%' FROM api.ventas),
                      'CALLFLOW ve la venta con el código del asesor');
RESET ROLE;
SET ROLE rumbo_app;

-- Llamar después: queda agendado
SELECT prueba.como(0);
SELECT set_config('prueba.lead2', (SELECT id::text FROM rumbo.lead WHERE telefono = '+593991000002'), true);
SELECT set_config('prueba.usuario_asesor',
                  (SELECT a.usuario_id::text FROM rumbo.lead l JOIN rumbo.asesor a ON a.id = l.asesor_id
                   WHERE l.id = current_setting('prueba.lead2')::bigint), true);
SELECT prueba.como(current_setting('prueba.usuario_asesor')::bigint);
SELECT rumbo.registrar_intento(current_setting('prueba.lead2')::bigint, NULL, 'llamar_despues', 'Después de las 5', now() + interval '1 day');
SELECT prueba.afirmar((SELECT proxima_accion_en > now() AND etapa_codigo = 'en_contacto' FROM rumbo.lead WHERE id = current_setting('prueba.lead2')::bigint),
                      'llamada agendada');

-- Descartar a mano exige motivo; reabrir es posible
SELECT prueba.debe_fallar(format($$SELECT rumbo.cambiar_etapa(%s, NULL, 'descartado')$$, current_setting('prueba.lead2')),
                          '23514', 'descartar a mano sin motivo');
SELECT rumbo.cambiar_etapa(current_setting('prueba.lead2')::bigint, NULL, 'descartado', 'precio');
SELECT rumbo.cambiar_etapa(current_setting('prueba.lead2')::bigint, NULL, 'en_contacto');
SELECT prueba.afirmar((SELECT estado_asignacion = 'asignado' AND motivo_descarte_codigo IS NULL FROM rumbo.lead WHERE id = current_setting('prueba.lead2')::bigint),
                      'lead descartado reabierto');

-- Supervisor reasigna a mano
SELECT prueba.como(2);
SELECT rumbo.reasignar_manual(current_setting('prueba.lead2')::bigint, prueba.asesor(13));
SELECT prueba.afirmar((SELECT asesor_id = prueba.asesor(13) FROM rumbo.lead WHERE id = current_setting('prueba.lead2')::bigint),
                      'reasignación manual del supervisor');

-- Estados de asesor: todos fuera de turno → el lead queda en cola, no se pierde
RESET ROLE;
SET ROLE rumbo_owner;
UPDATE rumbo.asesor SET estado = 'fuera_turno';
SET ROLE rumbo_app;
SELECT prueba.como(0);
SELECT * FROM prueba.mensaje('wamid.cola1', '+593991000099');
SELECT prueba.afirmar((SELECT estado_asignacion = 'en_cola' AND asesor_id IS NULL FROM rumbo.lead WHERE telefono = '+593991000099'),
                      'sin asesores en turno el lead queda en cola');
SELECT prueba.como(11);
SELECT rumbo.cambiar_estado_asesor('disponible');
SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT rumbo.liberar_cola() = 1), 'al volver un asesor se libera la cola');
SELECT prueba.afirmar((SELECT asesor_id = prueba.asesor(11) FROM rumbo.lead WHERE telefono = '+593991000099'),
                      'el lead de la cola llegó al asesor disponible');

-- Asesor ocupado: se le asigna a otro disponible; si todos ocupados igual se asigna
SELECT prueba.como(12);
SELECT rumbo.cambiar_estado_asesor('ocupado');
SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT asesor_id = prueba.asesor(11) FROM prueba.mensaje('wamid.oc1', '+593991000098')),
                      'lead nuevo va al disponible antes que al ocupado');
SELECT prueba.como(11);
SELECT rumbo.cambiar_estado_asesor('ocupado');
SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT asesor_id IS NOT NULL FROM prueba.mensaje('wamid.oc2', '+593991000097')),
                      'con todos ocupados el lead igual se asigna (no se pierde)');

-- Fuera de horario → cola
RESET ROLE;
SET ROLE rumbo_owner;
UPDATE rumbo.configuracion SET valor = '{"inicio": "00:00", "fin": "00:00:01", "dias": [1], "zona": "UTC"}' WHERE clave = 'horario';
SET ROLE rumbo_app;
SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT asesor_id IS NULL FROM prueba.mensaje('wamid.noche', '+593991000096')),
                      'lead fuera de horario queda en cola');
SELECT prueba.afirmar((SELECT rumbo.liberar_cola() = 0), 'fuera de horario no se reparte la cola');

-- Mensaje saliente desde el número del asesor (SCRUM-59)
SELECT prueba.como(11);
SELECT rumbo.registrar_mensaje_saliente((SELECT id FROM rumbo.lead WHERE telefono = '+593991000099'), 'wamid.out1', 'Hola, le escribo de Multivisa');
SELECT prueba.afirmar((SELECT numero_whatsapp_id = 1 AND direccion = 'saliente' FROM rumbo.mensaje_whatsapp WHERE wa_message_id = 'wamid.out1'),
                      'mensaje saliente sale por el número asignado al asesor');

-- LOPDP: anonimización
SELECT prueba.como(1);
SELECT rumbo.anonimizar_lead((SELECT id FROM rumbo.lead WHERE telefono = '+593991000099'));
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.lead WHERE telefono = '+593991000099'), 'teléfono eliminado al anonimizar');
SELECT prueba.afirmar((SELECT bool_and(cuerpo IS NULL) FROM rumbo.mensaje_whatsapp m JOIN rumbo.lead l ON l.id = m.lead_id
                       WHERE l.anonimizado_en IS NOT NULL), 'mensajes del lead anonimizados');
SELECT prueba.afirmar((SELECT NOT EXISTS (SELECT 1 FROM auditoria.registro WHERE antes::text LIKE '%593991000099%'
                                                                          OR despues::text LIKE '%593991000099%'
                                                                          OR cambios::text LIKE '%593991000099%')),
                      'el teléfono no quedó en claro en la auditoría');

RESET ROLE;
ROLLBACK;
