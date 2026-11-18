-- Sprint 2 · criterios de aceptación de SCRUM-22 (RF-03), SCRUM-24 (RF-10) y SCRUM-26 (RF-12)
-- Datos de _comun.sql: asesores 11 y 12 (número 1) y 13 (número 2), todos disponibles, horario 24/7.

-- Mensaje entrante con hora indicada (prueba.mensaje usa siempre now())
CREATE FUNCTION prueba.msg(p_wamid text, p_tel text, p_cuando timestamptz, p_nombre text DEFAULT 'Ana')
RETURNS TABLE (lead_id bigint, lead_nuevo boolean, mensaje_nuevo boolean, asesor_id bigint)
LANGUAGE sql AS $$
    SELECT * FROM rumbo.registrar_mensaje_entrante(p_wamid, p_tel, p_nombre, 1::smallint, 'text', 'Hola', '{}'::jsonb, p_cuando)
$$;
GRANT EXECUTE ON FUNCTION prueba.msg(text, text, timestamptz, text) TO PUBLIC;

SET ROLE rumbo_app;
SELECT prueba.como(0);

-- ───────────── RF-03 · Crear el lead automáticamente sin duplicados (SCRUM-22) ─────────────
SELECT * FROM prueba.msg('wamid.r1', '+593992000001', now() - interval '2 hours', 'Ana Pérez');
SELECT prueba.afirmar((SELECT nombre_perfil = 'Ana Pérez'
                              AND telefono = '+593992000001'
                              AND primer_contacto_en < now() - interval '119 minutes'
                       FROM rumbo.lead WHERE telefono = '+593992000001'),
                      'RF-03 · lead con nombre de perfil, número y fecha real del primer mensaje (no la de proceso)');

SELECT prueba.afirmar((SELECT NOT lead_nuevo AND mensaje_nuevo
                       FROM prueba.msg('wamid.r2', '+593992000001', now() - interval '1 hour')),
                      'RF-03 · mismo número, mensaje nuevo → se asocia al lead existente');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.lead WHERE telefono = '+593992000001')
                      AND (SELECT count(*) = 2 FROM rumbo.mensaje_whatsapp m JOIN rumbo.lead l ON l.id = m.lead_id
                           WHERE l.telefono = '+593992000001'),
                      'RF-03 · un lead, dos mensajes');

SELECT prueba.afirmar((SELECT NOT lead_nuevo AND NOT mensaje_nuevo
                       FROM prueba.msg('wamid.r2', '+593992000001', now() - interval '1 hour')),
                      'RF-03 · Meta reenvía el mismo id → ni lead ni mensaje duplicados');

-- Meta entregó tarde un mensaje anterior: el primer contacto se corrige hacia atrás
SELECT * FROM prueba.msg('wamid.r0', '+593992000001', now() - interval '3 hours');
SELECT prueba.afirmar((SELECT primer_contacto_en < now() - interval '179 minutes'
                              AND ultimo_mensaje_en > now() - interval '61 minutes'
                       FROM rumbo.lead WHERE telefono = '+593992000001'),
                      'RF-03 · mensaje fuera de orden: primer contacto = el más antiguo, último = el más reciente');

SELECT prueba.debe_fallar($$SELECT * FROM prueba.msg('wamid.bad', '0991234567', now())$$,
                          '23514', 'RF-03 · teléfono que no está en E.164 rechazado por la base');

-- ───────────── RF-10 · Reparto rotativo entre asesores en turno (SCRUM-24) ─────────────
-- Empezamos el turno desde cero para poder predecir el orden.
RESET ROLE; SET ROLE rumbo_owner;
UPDATE rumbo.asesor SET ultimo_lead_en = NULL;
SET ROLE rumbo_app;
SELECT prueba.como(0);

SELECT m.* FROM generate_series(1, 6) i, LATERAL prueba.msg('wamid.rr' || i, '+59399300000' || i, now()) m;
SELECT prueba.afirmar((SELECT array_agg(a.usuario_id ORDER BY l.telefono) = '{11,12,13,11,12,13}'
                       FROM rumbo.lead l JOIN rumbo.asesor a ON a.id = l.asesor_id
                       WHERE l.telefono LIKE '+59399300000%'),
                      'RF-10 · round robin en orden: A, B, C, A, B, C');

SELECT prueba.afirmar((SELECT count(*) = 6
                              AND bool_and(s.motivo = 'reparto' AND s.asesor_id = l.asesor_id
                                           AND s.asignado_por_usuario_id = 0 AND s.creado_en IS NOT NULL)
                       FROM rumbo.asignacion s JOIN rumbo.lead l ON l.id = s.lead_id
                       WHERE l.telefono LIKE '+59399300000%'),
                      'RF-10 · cada asignación queda registrada: a quién, cuándo, por qué y quién');

-- Solo reciben leads los asesores en turno: B en pausa y C fuera de turno → todo a A
SELECT prueba.como(2);
SELECT rumbo.cambiar_estado_asesor('pausa',       prueba.asesor(12));
SELECT rumbo.cambiar_estado_asesor('fuera_turno', prueba.asesor(13));
SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT bool_and(asesor_id = prueba.asesor(11))
                       FROM generate_series(1, 3) i, LATERAL prueba.msg('wamid.t' || i, '+59399400000' || i, now()) m),
                      'RF-10 · en pausa o fuera de turno no reciben leads');

-- Disponible antes que ocupado; si todos están ocupados, el lead igual se asigna
SELECT prueba.como(2);
SELECT rumbo.cambiar_estado_asesor('disponible', prueba.asesor(12));
SELECT rumbo.cambiar_estado_asesor('ocupado',    prueba.asesor(11));
SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT asesor_id = prueba.asesor(12) FROM prueba.msg('wamid.o1', '+593995000001', now())),
                      'RF-10 · se prefiere al disponible aunque al ocupado le toque por turno');
SELECT prueba.como(2);
SELECT rumbo.cambiar_estado_asesor('ocupado', prueba.asesor(12));
SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT asesor_id IS NOT NULL FROM prueba.msg('wamid.o2', '+593995000002', now())),
                      'RF-10 · todos ocupados: el lead se asigna igual (no se pierde)');

-- Nadie en turno → el lead queda en cola, sin asesor
SELECT prueba.como(2);
SELECT rumbo.cambiar_estado_asesor('fuera_turno', prueba.asesor(11));
SELECT rumbo.cambiar_estado_asesor('fuera_turno', prueba.asesor(12));
SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT asesor_id IS NULL FROM prueba.msg('wamid.c1', '+593996000001', now())),
                      'RF-10 · sin asesores en turno el lead queda en cola');
SELECT prueba.afirmar((SELECT estado_asignacion = 'en_cola' FROM rumbo.lead WHERE telefono = '+593996000001'),
                      'RF-10 · estado en_cola');

-- ───────────── RF-12 · El lead que vuelve a escribir conserva su asesor (SCRUM-26) ─────────────
-- '+593993000001' es de A (asesor 11). A está fuera de turno pero sigue activo → se queda con él.
SELECT prueba.afirmar((SELECT asesor_id = prueba.asesor(11) AND NOT lead_nuevo
                       FROM prueba.msg('wamid.v1', '+593993000001', now())),
                      'RF-12 · vuelve a escribir → mismo asesor, aunque esté fuera de turno o en pausa');
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.asignacion s JOIN rumbo.lead l ON l.id = s.lead_id
                       WHERE l.telefono = '+593993000001'),
                      'RF-12 · conservar el asesor no genera una reasignación');
SELECT prueba.afirmar((SELECT count(*) = 2 FROM rumbo.mensaje_whatsapp m JOIN rumbo.lead l ON l.id = m.lead_id
                       WHERE l.telefono = '+593993000001'),
                      'RF-12 · el mensaje nuevo queda en el historial del lead (para la ficha)');

-- El asesor 11 deja la empresa (usuario inactivo) → el lead entra al reparto normal
SELECT prueba.como(2);
SELECT rumbo.cambiar_estado_asesor('disponible', prueba.asesor(13));
RESET ROLE; SET ROLE rumbo_owner;
UPDATE rumbo.usuario SET activo = false WHERE id = 11;
SET ROLE rumbo_app;
SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT asesor_id = prueba.asesor(13) FROM prueba.msg('wamid.v2', '+593993000001', now())),
                      'RF-12 · si su asesor ya no está activo, entra al reparto normal');
SELECT prueba.afirmar((SELECT motivo = 'asesor_inactivo' AND asesor_anterior_id = prueba.asesor(11)
                       FROM rumbo.asignacion s JOIN rumbo.lead l ON l.id = s.lead_id
                       WHERE l.telefono = '+593993000001' ORDER BY s.id DESC LIMIT 1),
                      'RF-12 · reasignación registrada con motivo asesor_inactivo y el asesor anterior');

RESET ROLE;
ROLLBACK;
