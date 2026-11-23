-- 022 · SCRUM-54 · Límite de leads pendientes y peso de reparto. Datos de _comun.sql: asesores 11, 12 y 13.
CREATE FUNCTION prueba.reparto_limpio() RETURNS void
LANGUAGE sql SECURITY DEFINER AS $$
    UPDATE rumbo.asesor SET ultimo_lead_en = NULL, reparto_pase = 0, max_pendientes = NULL, peso_reparto = 1
$$;
CREATE FUNCTION prueba.recibidos(p_usuario_id bigint, p_prefijo text) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT count(*) FROM rumbo.lead l JOIN rumbo.asesor a ON a.id = l.asesor_id
    WHERE a.usuario_id = p_usuario_id AND l.telefono LIKE p_prefijo || '%'
$$;
CREATE FUNCTION prueba.cola(p_prefijo text) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT count(*) FROM rumbo.lead WHERE estado_asignacion = 'en_cola' AND telefono LIKE p_prefijo || '%'
$$;
CREATE FUNCTION prueba.agendar_todos(p_usuario_id bigint) RETURNS void
LANGUAGE sql SECURITY DEFINER AS $$
    UPDATE rumbo.lead SET proxima_accion_en = now() + interval '2 days'
    WHERE asesor_id = (SELECT id FROM rumbo.asesor WHERE usuario_id = p_usuario_id)
$$;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA prueba TO PUBLIC;

SET ROLE rumbo_app;

-- ───────────── Con todos en peso 1 sigue siendo round robin ─────────────
SELECT prueba.reparto_limpio();
SELECT prueba.como(0);
SELECT prueba.mensaje('wamid.rr' || g, '+59399910' || lpad(g::text, 4, '0')) FROM generate_series(1, 9) g;
SELECT prueba.afirmar(prueba.recibidos(11, '+59399910') = 3 AND prueba.recibidos(12, '+59399910') = 3
                      AND prueba.recibidos(13, '+59399910') = 3, '022 · peso 1 para todos: 3, 3 y 3 (round robin)');

-- ───────────── Peso 0.5: recibe la mitad ─────────────
SELECT prueba.como(1);
SELECT rumbo.guardar_carga_asesor(prueba.asesor(13), NULL, 0.5);
SELECT prueba.como(0);
SELECT prueba.mensaje('wamid.pe' || g, '+59399920' || lpad(g::text, 4, '0')) FROM generate_series(1, 10) g;
SELECT prueba.afirmar(prueba.recibidos(11, '+59399920') = 4 AND prueba.recibidos(12, '+59399920') = 4
                      AND prueba.recibidos(13, '+59399920') = 2,
                      '022 · el asesor con peso 0.5 recibe la mitad (4, 4 y 2 de 10)');

-- ───────────── Límite de pendientes: el que está lleno se salta ─────────────
SELECT prueba.como(1);
SELECT rumbo.guardar_carga_asesor(prueba.asesor(13), NULL, 1);
SELECT rumbo.guardar_carga_asesor(prueba.asesor(11), 8::smallint, 1);    -- ya tiene 3 + 4 = 7 por llamar
SELECT prueba.como(0);
SELECT prueba.mensaje('wamid.li' || g, '+59399930' || lpad(g::text, 4, '0')) FROM generate_series(1, 6) g;
SELECT prueba.afirmar(prueba.recibidos(11, '+59399930') = 1,
                      '022 · el asesor llega a su límite (8) y deja de recibir');
SELECT prueba.afirmar(prueba.recibidos(12, '+59399930') + prueba.recibidos(13, '+59399930') = 5,
                      '022 · los demás reciben el resto');
SELECT prueba.afirmar(rumbo.pendientes_asesor(prueba.asesor(11)) = 8, '022 · pendientes del asesor 11 = 8');

-- Las llamadas agendadas para más adelante no cuentan como pendientes.
SELECT prueba.agendar_todos(11);
SELECT prueba.afirmar(rumbo.pendientes_asesor(prueba.asesor(11)) = 0,
                      '022 · las llamadas agendadas a futuro no cuentan para el límite');

-- ───────────── Todos en el límite: el lead espera en cola y no se pierde ─────────────
SELECT prueba.como(1);
SELECT rumbo.guardar_carga_asesor(prueba.asesor(u), 1::smallint, 1) FROM unnest(ARRAY[11, 12, 13]) u;
SELECT prueba.como(0);
SELECT prueba.mensaje('wamid.co1', '+593999400001');
SELECT prueba.afirmar(prueba.recibidos(11, '+593999400001') = 1,
                      '022 · con 12 y 13 llenos, el lead va al único con lugar (11)');
SELECT prueba.mensaje('wamid.co2', '+593999400002');
SELECT prueba.afirmar(prueba.cola('+593999400002') = 1, '022 · si nadie tiene lugar, el lead queda en cola');
SELECT prueba.como(1);
SELECT rumbo.guardar_carga_asesor(prueba.asesor(12), NULL, 1);
SELECT prueba.como(0);
SELECT prueba.afirmar(rumbo.liberar_cola() >= 1, '022 · al liberarse un lugar, liberar_cola lo reparte');
SELECT prueba.afirmar(prueba.recibidos(12, '+593999400002') = 1, '022 · y lo recibe quien tiene lugar');

-- ───────────── Permisos y validación ─────────────
SELECT prueba.como(2);
SELECT prueba.debe_fallar($$SELECT rumbo.guardar_carga_asesor(prueba.asesor(12), 5::smallint, 1)$$, '42501',
                          '022 · solo el admin fija límites y pesos');
SELECT prueba.como(1);
SELECT prueba.debe_fallar($$SELECT rumbo.guardar_carga_asesor(prueba.asesor(12), 5::smallint, 0.05)$$, 'RB422',
                          '022 · el peso mínimo es 0.10');
SELECT prueba.debe_fallar($$SELECT rumbo.guardar_carga_asesor(prueba.asesor(12), 0::smallint, 1)$$, 'RB422',
                          '022 · el límite mínimo es 1');
RESET ROLE;
ROLLBACK;
