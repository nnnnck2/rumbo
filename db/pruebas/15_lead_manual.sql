-- 023 · SCRUM-53 · Registro manual de leads. Datos de _comun.sql: asesores 11, 12 y 13, horario 24/7.
CREATE FUNCTION prueba.lm(p_tel text) RETURNS rumbo.lead
LANGUAGE sql STABLE SECURITY DEFINER AS $$ SELECT * FROM rumbo.lead WHERE telefono = p_tel $$;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA prueba TO PUBLIC;
SET ROLE rumbo_app;

-- Un asesor registra un referido: queda con él (configuración por defecto).
SELECT prueba.como(11);
SELECT prueba.afirmar((SELECT r_nuevo AND r_asesor_id = prueba.asesor(11)
                       FROM rumbo.registrar_lead_manual('+593998800001', 'Pedro', 'referido', 'Turismo', 'España', 'Lo refirió Ana')),
                      '023 · el asesor registra un referido y queda asignado a él');
SELECT prueba.afirmar((SELECT origen = 'referido' AND tipo_visa = 'Turismo' AND pais_interes = 'España'
                              AND estado_asignacion = 'asignado' AND numero_whatsapp_id IS NULL
                       FROM prueba.lm('+593998800001')), '023 · guarda canal, visa y país');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.nota_lead n JOIN rumbo.lead l ON l.id = n.lead_id
                       WHERE l.telefono = '+593998800001'), '023 · la nota queda en la ficha');
SELECT prueba.afirmar((SELECT motivo = 'manual' FROM rumbo.asignacion s JOIN rumbo.lead l ON l.id = s.lead_id
                       WHERE l.telefono = '+593998800001'), '023 · la asignación queda en el historial');

-- Duplicado: no crea otro y devuelve el existente.
SELECT prueba.como(12);
SELECT prueba.afirmar((SELECT NOT r_nuevo AND r_lead_id = (prueba.lm('+593998800001')).id
                       FROM rumbo.registrar_lead_manual('+593998800001', 'Otro', 'llamada')),
                      '023 · un número ya registrado no se duplica');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.registrar_lead_manual('+593998800001', 'Otro', 'llamada')),
                      '023 · y se informa el lead existente');

-- Configuración: entra al reparto. Un supervisor siempre lo manda al reparto.
SELECT prueba.como(1);
UPDATE rumbo.configuracion SET valor = '{"asignar_a_quien_registra": false}' WHERE clave = 'lead_manual';
SELECT prueba.como(11);
SELECT * FROM rumbo.registrar_lead_manual('+593998800002', 'Rosa', 'llamada');
SELECT prueba.afirmar((prueba.lm('+593998800002')).estado_asignacion = 'asignado'
                      AND (SELECT motivo = 'reparto' FROM rumbo.asignacion WHERE lead_id = (prueba.lm('+593998800002')).id),
                      '023 · con la opción desactivada entra al reparto');
SELECT prueba.como(2);
SELECT * FROM rumbo.registrar_lead_manual('+593998800003', 'Luis', 'visita');
SELECT prueba.afirmar((SELECT motivo = 'reparto' FROM rumbo.asignacion WHERE lead_id = (prueba.lm('+593998800003')).id),
                      '023 · lo que registra un supervisor entra al reparto');

-- Validaciones
SELECT prueba.debe_fallar($$SELECT * FROM rumbo.registrar_lead_manual('0991234567', 'x', 'llamada')$$, 'RB422',
                          '023 · el teléfono debe venir en formato internacional');
SELECT prueba.debe_fallar($$SELECT * FROM rumbo.registrar_lead_manual('+593998800009', 'x', 'whatsapp')$$, 'RB422',
                          '023 · el canal whatsapp no se registra a mano');
SELECT prueba.como(0);
SELECT prueba.debe_fallar($$SELECT * FROM rumbo.registrar_lead_manual('+593998800009', 'x', 'llamada')$$, '42501',
                          '023 · el sistema no registra leads manuales');

-- Si el cliente escribe después por WhatsApp, el lead toma el número de la empresa y no se duplica.
SELECT prueba.mensaje('wamid.lm1', '+593998800001');
SELECT prueba.afirmar((SELECT numero_whatsapp_id = 1 AND asesor_id = prueba.asesor(11) FROM prueba.lm('+593998800001')),
                      '023 · al escribir por WhatsApp sigue con su asesor y toma el número de la empresa');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.lead WHERE telefono = '+593998800001'),
                      '023 · sin lead duplicado');
RESET ROLE;
ROLLBACK;
