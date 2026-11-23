-- 025 · SCRUM-43 · LOPDP: aviso de privacidad y consentimiento del titular.
CREATE FUNCTION prueba.lc(p_tel text) RETURNS rumbo.lead
LANGUAGE sql STABLE SECURITY DEFINER AS $$ SELECT * FROM rumbo.lead WHERE telefono = p_tel $$;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA prueba TO PUBLIC;
SET ROLE rumbo_app;

-- La respuesta automática lleva el aviso de privacidad configurado.
SELECT prueba.como(0);
SELECT prueba.mensaje('wamid.lopdp1', '+593996600001');
SELECT rumbo.registrar_respuesta_automatica((prueba.lc('+593996600001')).id, 'wamid.auto.lopdp1',
       '¡Hola, te saluda Multivisa!' || E'\n\n' || (SELECT valor #>> '{}' FROM rumbo.configuracion WHERE clave = 'texto_privacidad'));
SELECT prueba.como((SELECT a.usuario_id FROM rumbo.asesor a WHERE a.id = (prueba.lc('+593996600001')).asesor_id));
SELECT prueba.afirmar(rumbo.aviso_privacidad_enviado((prueba.lc('+593996600001')).id) IS NOT NULL,
                      '025 · se sabe cuándo recibió el aviso de privacidad');
SELECT prueba.afirmar((prueba.lc('+593996600001')).consentimiento_en IS NULL, '025 · el consentimiento empieza sin registrar');

-- El asesor dueño registra el consentimiento con el medio; no se pisa.
SELECT prueba.afirmar(rumbo.registrar_consentimiento((prueba.lc('+593996600001')).id, 'llamada'),
                      '025 · el asesor registra el consentimiento');
SELECT prueba.afirmar((SELECT consentimiento_en IS NOT NULL AND datos -> 'consentimiento' ->> 'medio' = 'llamada'
                       FROM prueba.lc('+593996600001')), '025 · queda la fecha y la evidencia (medio y usuario)');
SELECT prueba.afirmar(NOT rumbo.registrar_consentimiento((prueba.lc('+593996600001')).id, 'whatsapp'),
                      '025 · la primera constancia no se pisa');
SELECT prueba.como(1);       -- la auditoría solo la lee el admin
SELECT prueba.afirmar((SELECT count(*) >= 1 FROM auditoria.registro r
                       WHERE r.tabla = 'rumbo.lead' AND r.cambios ? 'consentimiento_en'
                         AND r.registro_id = (prueba.lc('+593996600001')).id::text),
                      '025 · el registro del consentimiento queda en la auditoría');
SELECT prueba.debe_fallar($$SELECT rumbo.registrar_consentimiento((prueba.lc('+593996600001')).id, 'adivinado')$$,
                          'RB422', '025 · el medio debe ser uno válido');

-- Otro asesor no puede registrar consentimiento en un lead ajeno.
SELECT prueba.como(0);
SELECT prueba.mensaje('wamid.lopdp2', '+593996600002');
SELECT prueba.como((SELECT a.usuario_id FROM rumbo.asesor a WHERE a.id <> (prueba.lc('+593996600002')).asesor_id LIMIT 1));
SELECT prueba.debe_fallar($$SELECT rumbo.registrar_consentimiento((prueba.lc('+593996600002')).id, 'llamada')$$,
                          '42501', '025 · un asesor no registra consentimiento en un lead ajeno');

-- Alta manual con consentimiento.
SELECT prueba.como(12);
SELECT * FROM rumbo.registrar_lead_manual('+593996600003', 'Ana', 'visita', NULL, NULL, NULL, true);
SELECT prueba.afirmar((SELECT consentimiento_en IS NOT NULL AND datos -> 'consentimiento' ->> 'medio' = 'presencial'
                       FROM prueba.lc('+593996600003')), '025 · el alta manual registra el consentimiento presencial');
SELECT * FROM rumbo.registrar_lead_manual('+593996600004', 'Beto', 'llamada');
SELECT prueba.afirmar((prueba.lc('+593996600004')).consentimiento_en IS NULL, '025 · sin marcarlo no se registra');
RESET ROLE;
ROLLBACK;
