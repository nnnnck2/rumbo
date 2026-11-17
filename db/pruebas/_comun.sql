-- Utilidades y datos de prueba. Se antepone a cada archivo de prueba.
-- Todo corre dentro de una transacción que se revierte al final (ROLLBACK).
\set ON_ERROR_STOP 1
\set QUIET 1
SET client_min_messages = notice;
BEGIN;

CREATE SCHEMA prueba;
GRANT USAGE ON SCHEMA prueba TO PUBLIC;

CREATE FUNCTION prueba.afirmar(p_condicion boolean, p_mensaje text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    IF p_condicion IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'FALLÓ: %', p_mensaje;
    END IF;
    RAISE NOTICE 'ok · %', p_mensaje;
END $$;

-- Ejecuta p_sql y exige que falle con el SQLSTATE indicado.
CREATE FUNCTION prueba.debe_fallar(p_sql text, p_sqlstate text, p_mensaje text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE p_sql;
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE = p_sqlstate THEN
            RAISE NOTICE 'ok · % → rechazado (%)', p_mensaje, SQLSTATE;
            RETURN;
        END IF;
        RAISE EXCEPTION 'FALLÓ: % → error % (%), se esperaba %', p_mensaje, SQLSTATE, SQLERRM, p_sqlstate;
    END;
    RAISE EXCEPTION 'FALLÓ: % → se esperaba error % y no hubo', p_mensaje, p_sqlstate;
END $$;

CREATE FUNCTION prueba.como(p_usuario_id bigint) RETURNS void
LANGUAGE sql AS $$ SELECT set_config('rumbo.usuario_id', p_usuario_id::text, true) $$;

GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA prueba TO PUBLIC;

-- Datos de prueba (como dueño, sin RLS)
SET ROLE rumbo_owner;
INSERT INTO rumbo.usuario (id, nombre, rol) VALUES
    (1, 'Admin',       'admin'),
    (2, 'Supervisora', 'supervisor'),
    (11, 'Asesor A',   'asesor'),
    (12, 'Asesor B',   'asesor'),
    (13, 'Asesor C',   'asesor');
INSERT INTO rumbo.asesor (usuario_id, numero_whatsapp_id, codigo_callflow, estado) VALUES
    (11, 1, 'EMP-011', 'disponible'),
    (12, 1, 'EMP-012', 'disponible'),
    (13, 2, 'EMP-013', 'disponible');
-- Horario 24/7 para que las pruebas no dependan de la hora
UPDATE rumbo.configuracion
SET valor = '{"inicio": "00:00", "fin": "23:59:59", "dias": [1,2,3,4,5,6,7], "zona": "UTC"}'
WHERE clave = 'horario';
RESET ROLE;

CREATE FUNCTION prueba.asesor(p_usuario_id bigint) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER AS $$ SELECT id FROM rumbo.asesor WHERE usuario_id = p_usuario_id $$;
GRANT EXECUTE ON FUNCTION prueba.asesor(bigint) TO PUBLIC;

-- Mensaje entrante de prueba (como sistema)
CREATE FUNCTION prueba.mensaje(p_wamid text, p_telefono text, p_nombre text DEFAULT 'Cliente')
RETURNS TABLE (lead_id bigint, lead_nuevo boolean, mensaje_nuevo boolean, asesor_id bigint)
LANGUAGE sql AS $$
    SELECT * FROM rumbo.registrar_mensaje_entrante(p_wamid, p_telefono, p_nombre, 1::smallint, 'text', 'Hola', '{}'::jsonb, now())
$$;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA prueba TO PUBLIC;
