-- Sprint 4 · criterios de SCRUM-36 (RF-23), SCRUM-37 (RF-24), SCRUM-38 (RF-13), SCRUM-39 (RF-14), SCRUM-40 (RF-33)
-- Datos de _comun.sql: asesores 11, 12 y 13 disponibles. Horario: ver prueba.horario().
CREATE FUNCTION prueba.msg_en(p_wamid text, p_tel text, p_cuando timestamptz)
RETURNS TABLE (lead_id bigint, lead_nuevo boolean, mensaje_nuevo boolean, asesor_id bigint)
LANGUAGE sql AS $$
    SELECT * FROM rumbo.registrar_mensaje_entrante(p_wamid, p_tel, 'Cliente', 1::smallint, 'text', 'Hola', '{}'::jsonb, p_cuando)
$$;
CREATE FUNCTION prueba.lead(p_tel text) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER AS $$ SELECT id FROM rumbo.lead WHERE telefono = p_tel $$;
CREATE FUNCTION prueba.version(p_tel text) RETURNS integer
LANGUAGE sql STABLE SECURITY DEFINER AS $$ SELECT version FROM rumbo.lead WHERE telefono = p_tel $$;
CREATE FUNCTION prueba.usuario_dueno(p_tel text) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT a.usuario_id FROM rumbo.lead l JOIN rumbo.asesor a ON a.id = l.asesor_id WHERE l.telefono = p_tel $$;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA prueba TO PUBLIC;

-- Zona horaria en la que ahora son ~las 12:00 (Etc/GMT±N): las pruebas de horario no dependen
-- de la hora en que se corran (nunca cruzan la medianoche).
CREATE FUNCTION prueba.zona_mediodia() RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT 'Etc/GMT' || CASE WHEN n >= 0 THEN '+' || n ELSE n::text END
    FROM (SELECT extract(hour FROM now() AT TIME ZONE 'UTC')::int - 12 AS n) x
$$;
-- Horario de atención en esa zona (lo cambia el admin, como desde el panel)
CREATE FUNCTION prueba.horario(p_inicio text, p_fin text DEFAULT '23:59:59') RETURNS void
LANGUAGE sql AS $$
    UPDATE rumbo.configuracion
    SET valor = jsonb_build_object('inicio', p_inicio, 'fin', p_fin, 'dias', '[1,2,3,4,5,6,7]'::jsonb,
                                   'zona', prueba.zona_mediodia())
    WHERE clave = 'horario'
$$;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA prueba TO PUBLIC;

SET ROLE rumbo_app;
SELECT prueba.como(1);
SELECT prueba.horario('00:00');

-- ───────────── RF-23 · Política de reintentos configurable (SCRUM-36) ─────────────
SELECT prueba.como(1);
UPDATE rumbo.configuracion SET valor = '2' WHERE clave = 'max_intentos_por_asesor';
UPDATE rumbo.configuracion SET valor = '20' WHERE clave = 'minutos_entre_reintentos';
SELECT prueba.como(0);
SELECT * FROM prueba.msg_en('wamid.op1', '+593997000001', now());
SELECT set_config('prueba.u1', prueba.usuario_dueno('+593997000001')::text, true);
SELECT prueba.como(current_setting('prueba.u1')::bigint);
SELECT rumbo.registrar_intento(prueba.lead('+593997000001'), NULL, 'no_contesta');
SELECT prueba.afirmar((SELECT proxima_accion_en BETWEEN now() + interval '19 minutes' AND now() + interval '21 minutes'
                       FROM rumbo.lead WHERE telefono = '+593997000001'),
                      'RF-23 · no contesta programa el reintento según minutos_entre_reintentos (20)');
SELECT rumbo.registrar_intento(prueba.lead('+593997000001'), NULL, 'no_contesta');
SELECT prueba.como(1);
SELECT prueba.afirmar((SELECT a.usuario_id::text <> current_setting('prueba.u1') AND l.intentos_asesor_actual = 0
                       FROM rumbo.lead l JOIN rumbo.asesor a ON a.id = l.asesor_id WHERE l.telefono = '+593997000001'),
                      'RF-23 · con el máximo configurado en 2, al 2.º intento pasa al siguiente asesor');
SELECT prueba.como(prueba.usuario_dueno('+593997000001'));
SELECT prueba.afirmar((SELECT count(*) = 2 FROM rumbo.intento_llamada WHERE lead_id = prueba.lead('+593997000001')),
                      'RF-23 · el nuevo asesor ve el historial de intentos del asesor anterior');
SELECT prueba.como(1);
UPDATE rumbo.configuracion SET valor = '3' WHERE clave = 'max_intentos_por_asesor';
UPDATE rumbo.configuracion SET valor = '30' WHERE clave = 'minutos_entre_reintentos';

-- ───────────── RF-24 · Agendar llamada (SCRUM-37) ─────────────
SELECT prueba.como(0);
SELECT * FROM prueba.msg_en('wamid.ag1', '+593997100001', now());
SELECT prueba.como(prueba.usuario_dueno('+593997100001'));
SELECT rumbo.agendar_llamada(prueba.lead('+593997100001'), prueba.version('+593997100001'), now() + interval '1 day');
SELECT prueba.afirmar((SELECT proxima_accion_en > now() + interval '23 hours' AND intentos_totales = 0
                       FROM rumbo.lead WHERE telefono = '+593997100001'),
                      'RF-24 · agendar desde la ficha fija la próxima llamada sin contar un intento');
SELECT prueba.debe_fallar(format($$SELECT rumbo.agendar_llamada(%s, NULL, now() - interval '1 hour')$$, prueba.lead('+593997100001')),
                          'RB422', 'RF-24 · no se agenda en el pasado');
SELECT prueba.debe_fallar(format($$SELECT rumbo.agendar_llamada(%s, 1, now() + interval '1 hour')$$, prueba.lead('+593997100001')),
                          'RB409', 'RF-24 · versión vieja rechazada');
SELECT prueba.como(CASE WHEN prueba.usuario_dueno('+593997100001') = 11 THEN 12 ELSE 11 END);
SELECT prueba.debe_fallar(format($$SELECT rumbo.agendar_llamada(%s, NULL, now() + interval '1 hour')$$, prueba.lead('+593997100001')),
                          '42501', 'RF-24 · un asesor no agenda leads ajenos');

-- Agendada en el futuro: no cuenta como "no llamó a tiempo"
RESET ROLE; SET ROLE rumbo_owner;
UPDATE rumbo.lead SET asignado_en = now() - interval '2 hours' WHERE telefono = '+593997100001';
SET ROLE rumbo_app;
SELECT prueba.como(0);
SELECT rumbo.reasignar_sin_primera_llamada();
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.asignacion WHERE lead_id = prueba.lead('+593997100001') AND motivo = 'sin_primera_llamada'),
                      'RF-24 · un lead con llamada agendada no se reasigna por falta de primera llamada');

-- ───────────── RF-14 · Reasignación si no llama a tiempo (SCRUM-39) ─────────────
SELECT prueba.como(0);
SELECT * FROM prueba.msg_en('wamid.rf14a', '+593997200001', now());
SELECT * FROM prueba.msg_en('wamid.rf14b', '+593997200002', now());
SELECT set_config('prueba.dueno_a', prueba.usuario_dueno('+593997200001')::text, true);
RESET ROLE; SET ROLE rumbo_owner;
UPDATE rumbo.lead SET asignado_en = now() - interval '20 minutes', proxima_accion_en = now() - interval '20 minutes'
WHERE telefono IN ('+593997200001', '+593997200002');
SET ROLE rumbo_app;
-- El dueño de B sí llamó
SELECT prueba.como(prueba.usuario_dueno('+593997200002'));
SELECT rumbo.registrar_intento(prueba.lead('+593997200002'), NULL, 'interesado');
SELECT prueba.como(0);
SELECT rumbo.reasignar_sin_primera_llamada();
SELECT prueba.como(1);
SELECT prueba.afirmar((SELECT prueba.usuario_dueno('+593997200001')::text <> current_setting('prueba.dueno_a')),
                      'RF-14 · sin primer intento en 15 min → pasa a otro asesor');
SELECT prueba.afirmar((SELECT motivo = 'sin_primera_llamada' AND asesor_anterior_id IS NOT NULL AND asignado_por_usuario_id = 0
                       FROM rumbo.asignacion WHERE lead_id = prueba.lead('+593997200001') ORDER BY id DESC LIMIT 1),
                      'RF-14 · la reasignación automática queda registrada (motivo, asesor anterior, sistema)');
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.asignacion WHERE lead_id = prueba.lead('+593997200002') AND motivo = 'sin_primera_llamada'),
                      'RF-14 · el lead que sí se llamó no se reasigna');

-- Corrección de 013: lo asignado antes de la apertura no vence apenas abre el turno.
-- Apertura hace 5 minutos.
SELECT prueba.como(1);
SELECT prueba.horario(to_char((now() AT TIME ZONE prueba.zona_mediodia()) - interval '5 minutes', 'HH24:MI'));
SELECT prueba.como(0);
SELECT * FROM prueba.msg_en('wamid.rf14c', '+593997200003', now());
SELECT set_config('prueba.dueno_c', prueba.usuario_dueno('+593997200003')::text, true);
RESET ROLE; SET ROLE rumbo_owner;
UPDATE rumbo.lead SET asignado_en = rumbo.inicio_turno() - interval '15 hours',
                      proxima_accion_en = rumbo.inicio_turno() - interval '15 hours'
WHERE telefono = '+593997200003';
SET ROLE rumbo_app;
SELECT rumbo.reasignar_sin_primera_llamada();
SELECT prueba.afirmar((SELECT prueba.usuario_dueno('+593997200003')::text = current_setting('prueba.dueno_c')),
                      'RF-14 · asignado ayer al cierre: a los 5 min de abrir sigue con su asesor (no cuenta la noche)');

-- ───────────── RF-13 · Cola de fuera de horario (SCRUM-38) ─────────────
-- Cerrado: horario que terminó hace más de una hora (o que empieza más tarde)
SELECT prueba.como(1);
SELECT prueba.horario('00:00', '00:01');
SELECT prueba.afirmar((SELECT NOT rumbo.en_horario()), 'RF-13 · horario cerrado para la prueba');
SELECT prueba.como(0);
SELECT * FROM prueba.msg_en('wamid.cola3', '+593997300003', now() - interval '10 minutes');
SELECT * FROM prueba.msg_en('wamid.cola1', '+593997300001', now() - interval '50 minutes');
SELECT * FROM prueba.msg_en('wamid.cola2', '+593997300002', now() - interval '30 minutes');
SELECT prueba.afirmar((SELECT bool_and(estado_asignacion = 'en_cola' AND asesor_id IS NULL)
                       FROM rumbo.lead WHERE telefono LIKE '+59399730000%'),
                      'RF-13 · fuera de horario los leads quedan en cola, sin asesor');
SELECT prueba.afirmar((SELECT rumbo.liberar_cola() = 0), 'RF-13 · fuera de horario la cola no se reparte');
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.leads_sin_llamar()), 'RF-33 · fuera de horario no hay alertas');

-- Abre el turno (el horario se cambia desde la configuración)
SELECT prueba.como(1);
SELECT prueba.horario('00:00');
SELECT prueba.como(0);
SELECT prueba.afirmar((SELECT rumbo.liberar_cola() >= 3), 'RF-13 · al abrir, la cola se reparte');
SELECT prueba.afirmar((SELECT array_agg(l.telefono::text ORDER BY s.id) = '{+593997300001,+593997300002,+593997300003}'
                       FROM rumbo.asignacion s JOIN rumbo.lead l ON l.id = s.lead_id
                       WHERE l.telefono LIKE '+59399730000%' AND s.motivo = 'cola_horario'),
                      'RF-13 · se reparte en orden de llegada (hora real del mensaje)');
SELECT prueba.afirmar((SELECT count(DISTINCT asesor_id) = 3 FROM rumbo.lead WHERE telefono LIKE '+59399730000%'),
                      'RF-13 · repartidos entre los asesores disponibles (round robin)');

-- ───────────── RF-33 · Alerta al supervisor (SCRUM-40) ─────────────
SELECT prueba.como(0);
SELECT * FROM prueba.msg_en('wamid.al1', '+593997400001', now());
SELECT * FROM prueba.msg_en('wamid.al2', '+593997400002', now());
RESET ROLE; SET ROLE rumbo_owner;
UPDATE rumbo.lead SET proxima_accion_en = now() - interval '40 minutes' WHERE telefono = '+593997400001';
UPDATE rumbo.lead SET proxima_accion_en = now() - interval '10 minutes' WHERE telefono = '+593997400002';
SET ROLE rumbo_app;
SELECT prueba.como(2);   -- supervisora
SELECT prueba.afirmar((SELECT motivo = 'sin_primera_llamada' AND minutos BETWEEN 39 AND 41 AND asesor IS NOT NULL
                       FROM rumbo.leads_sin_llamar() WHERE telefono = '+593997400001'),
                      'RF-33 · alerta con lead, asesor y tiempo de espera (40 min > umbral 30)');
SELECT prueba.afirmar((SELECT count(*) = 0 FROM rumbo.leads_sin_llamar() WHERE telefono = '+593997400002'),
                      'RF-33 · 10 min de atraso: todavía no alerta');
SELECT prueba.como(1);
UPDATE rumbo.configuracion SET valor = '5' WHERE clave = 'minutos_alerta_supervisor';
SELECT prueba.como(2);
SELECT prueba.afirmar((SELECT count(*) = 1 FROM rumbo.leads_sin_llamar() WHERE telefono = '+593997400002'),
                      'RF-33 · umbral configurable: con 5 min ya alerta');
UPDATE rumbo.configuracion SET valor = '60' WHERE clave = 'minutos_alerta_supervisor';   -- RLS: 0 filas
SELECT prueba.afirmar((SELECT valor = '5'::jsonb FROM rumbo.configuracion WHERE clave = 'minutos_alerta_supervisor'),
                      'RF-33 · la supervisora no puede cambiar el umbral (RLS)');
SELECT prueba.como(1);
SELECT prueba.debe_fallar($$UPDATE rumbo.configuracion SET valor = '0' WHERE clave = 'minutos_alerta_supervisor'$$,
                          'RB422', 'RF-33 · umbral fuera de rango rechazado');
-- El asesor solo ve sus propias alertas
SELECT prueba.como(prueba.usuario_dueno('+593997400001'));
SELECT prueba.afirmar((SELECT bool_and(asesor_id = rumbo.ctx_asesor_id()) FROM rumbo.leads_sin_llamar()),
                      'RF-33 · un asesor solo ve sus propios leads atrasados (RLS)');

RESET ROLE;
ROLLBACK;
