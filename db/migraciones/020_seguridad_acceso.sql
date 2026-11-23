-- 020 · SCRUM-35 · Seguridad de acceso: registro de ingresos y bloqueo temporal tras varios fallos
--   · auditoria.acceso: cada ingreso correcto, fallido, bloqueado y cada salida (solo inserción, inmutable).
--   · auditoria.registrar_acceso(): lo llama el login ANTES de autenticar (sin contexto de usuario), por eso
--     es SECURITY DEFINER y solo inserta.
--   · auditoria.bloqueo_acceso(): si el usuario (o la IP) acumuló demasiados fallos recientes, devuelve hasta
--     cuándo está bloqueado. Se calcula en la base, así vale igual para todos los procesos de gunicorn.
--     Política: 5 fallos en 15 min para un usuario → 15 min bloqueado; 30 fallos en 15 min desde una
--     misma IP → 15 min bloqueada (alguien probando muchos usuarios). Un ingreso correcto reinicia la
--     cuenta del usuario.
--   · Las reasignaciones y los cambios de configuración ya quedan en rumbo.asignacion y auditoria.registro (005);
--     la pantalla de Auditoría (Django, solo admin) muestra las tres cosas juntas.

CREATE TABLE auditoria.acceso (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ocurrido_en  timestamptz NOT NULL DEFAULT clock_timestamp(),
    usuario      text        NOT NULL CHECK (length(usuario) <= 150),      -- lo que escribió (en minúsculas)
    usuario_id   bigint,                                                   -- si el usuario existe
    evento       text        NOT NULL CHECK (evento IN ('ingreso', 'fallido', 'bloqueado', 'salida')),
    ip           inet,
    agente       text        CHECK (length(agente) <= 300)
);
CREATE INDEX acceso_usuario_ix  ON auditoria.acceso (usuario, ocurrido_en DESC);
CREATE INDEX acceso_ip_ix       ON auditoria.acceso (ip, ocurrido_en DESC) WHERE evento = 'fallido';
CREATE INDEX acceso_tiempo_brin ON auditoria.acceso USING brin (ocurrido_en);

CREATE TRIGGER acceso_inmutable    BEFORE UPDATE OR DELETE ON auditoria.acceso
    FOR EACH ROW EXECUTE FUNCTION auditoria.tg_inmutable();
CREATE TRIGGER acceso_sin_truncate BEFORE TRUNCATE ON auditoria.acceso
    FOR EACH STATEMENT EXECUTE FUNCTION auditoria.tg_inmutable();

CREATE FUNCTION auditoria.registrar_acceso(p_usuario text, p_evento text, p_ip inet DEFAULT NULL,
                                           p_agente text DEFAULT NULL, p_usuario_id bigint DEFAULT NULL)
RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$
    INSERT INTO auditoria.acceso (usuario, usuario_id, evento, ip, agente)
    VALUES (left(lower(btrim(coalesce(p_usuario, ''))), 150), p_usuario_id, p_evento, p_ip, left(p_agente, 300))
$$;

-- Hasta cuándo está bloqueado el ingreso para este usuario / IP (NULL = puede intentar).
CREATE FUNCTION auditoria.bloqueo_acceso(p_usuario text, p_ip inet,
                                         p_fallos_usuario integer DEFAULT 5, p_fallos_ip integer DEFAULT 30,
                                         p_ventana interval DEFAULT interval '15 minutes',
                                         p_bloqueo interval DEFAULT interval '15 minutes')
RETURNS timestamptz
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_usuario      text := left(lower(btrim(coalesce(p_usuario, ''))), 150);
    v_ultimo_ok    timestamptz;
    v_fallos       timestamptz[];
    v_hasta        timestamptz;
BEGIN
    -- Por usuario: fallos dentro de la ventana y posteriores a su último ingreso correcto.
    SELECT max(a.ocurrido_en) INTO v_ultimo_ok
    FROM auditoria.acceso a WHERE a.usuario = v_usuario AND a.evento = 'ingreso';

    SELECT array_agg(a.ocurrido_en ORDER BY a.ocurrido_en DESC) INTO v_fallos
    FROM auditoria.acceso a
    WHERE a.usuario = v_usuario AND a.evento = 'fallido'
      AND a.ocurrido_en > greatest(now() - p_ventana - p_bloqueo, coalesce(v_ultimo_ok, '-infinity'));
    -- El bloqueo dura p_bloqueo desde el fallo que completó el cupo dentro de una ventana.
    IF cardinality(v_fallos) >= p_fallos_usuario
       AND v_fallos[1] - v_fallos[p_fallos_usuario] <= p_ventana THEN
        v_hasta := v_fallos[1] + p_bloqueo;
    END IF;

    IF p_ip IS NOT NULL THEN
        SELECT array_agg(a.ocurrido_en ORDER BY a.ocurrido_en DESC) INTO v_fallos
        FROM auditoria.acceso a
        WHERE a.ip = p_ip AND a.evento = 'fallido' AND a.ocurrido_en > now() - p_ventana - p_bloqueo;
        IF cardinality(v_fallos) >= p_fallos_ip
           AND v_fallos[1] - v_fallos[p_fallos_ip] <= p_ventana THEN
            v_hasta := greatest(v_hasta, v_fallos[1] + p_bloqueo);
        END IF;
    END IF;

    RETURN CASE WHEN v_hasta > now() THEN v_hasta END;
END $$;

-- Lectura para la pantalla de Auditoría: solo el administrador (la tabla no tiene GRANT de SELECT).
CREATE FUNCTION auditoria.accesos_recientes(p_limite integer DEFAULT 200, p_evento text DEFAULT NULL)
RETURNS SETOF auditoria.acceso
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    PERFORM rumbo._exigir_rol('admin');
    RETURN QUERY
    SELECT * FROM auditoria.acceso a
    WHERE p_evento IS NULL OR a.evento = p_evento
    ORDER BY a.id DESC LIMIT least(greatest(p_limite, 1), 1000);
END $$;

REVOKE ALL ON FUNCTION auditoria.registrar_acceso(text, text, inet, text, bigint),
                       auditoria.bloqueo_acceso(text, inet, integer, integer, interval, interval),
                       auditoria.accesos_recientes(integer, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auditoria.registrar_acceso(text, text, inet, text, bigint),
                          auditoria.bloqueo_acceso(text, inet, integer, integer, interval, interval),
                          auditoria.accesos_recientes(integer, text) TO rumbo_app;
