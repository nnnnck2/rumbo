-- 005 · Auditoría inmutable
-- Cada INSERT/UPDATE/DELETE en las tablas auditadas deja una fila con: quién (usuario de la
-- app y rol de BD), desde dónde (IP, aplicación), cuándo, en qué transacción y qué cambió.
-- Los datos personales (teléfono, nombre, cuerpo de mensajes) NO se copian en claro: se
-- guarda un hash, así la auditoría no se convierte en una segunda copia de datos sensibles
-- y anonimizar un lead (LOPDP) no obliga a reescribir la auditoría.

CREATE TABLE auditoria.registro (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ocurrido_en  timestamptz NOT NULL DEFAULT clock_timestamp(),
    transaccion  xid8        NOT NULL DEFAULT pg_current_xact_id(),
    tabla        text        NOT NULL,
    operacion    text        NOT NULL CHECK (operacion IN ('INSERT', 'UPDATE', 'DELETE')),
    registro_id  text,
    usuario_id   bigint,                         -- usuario de la app (contexto de sesión)
    rol_bd       text        NOT NULL DEFAULT session_user,
    cliente_ip   inet                 DEFAULT inet_client_addr(),
    aplicacion   text                 DEFAULT nullif(current_setting('application_name', true), ''),
    antes        jsonb,
    despues      jsonb,
    cambios      jsonb                           -- solo UPDATE: {"columna": {"antes": .., "despues": ..}}
);

CREATE INDEX registro_tiempo_brin ON auditoria.registro USING brin (ocurrido_en);
CREATE INDEX registro_fila_ix     ON auditoria.registro (tabla, registro_id, id);
CREATE INDEX registro_usuario_ix  ON auditoria.registro (usuario_id, ocurrido_en) WHERE usuario_id IS NOT NULL;

-- Hash corto de un valor: permite saber que cambió (y comparar), no cuál era.
CREATE FUNCTION auditoria.hash_valor(p_valor jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path = pg_catalog AS $$
    SELECT CASE WHEN p_valor IS NULL OR p_valor = 'null'::jsonb THEN p_valor
                ELSE to_jsonb('sha256:' || left(encode(sha256(convert_to(p_valor::text, 'UTF8')), 'hex'), 16)) END
$$;

-- Reemplaza las columnas sensibles de una fila por su hash.
CREATE FUNCTION auditoria.enmascarar(p_fila jsonb, p_sensibles text[]) RETURNS jsonb
LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path = pg_catalog AS $$
    SELECT CASE WHEN p_fila IS NULL THEN NULL ELSE
           coalesce(jsonb_object_agg(e.key,
                        CASE WHEN e.key = ANY (p_sensibles) THEN auditoria.hash_valor(e.value) ELSE e.value END),
                    '{}'::jsonb) END
    FROM jsonb_each(p_fila) e
$$;

-- Trigger genérico. Argumentos:
--   TG_ARGV[0] = columnas a ignorar al decidir si hubo cambio (separadas por coma)
--   TG_ARGV[1] = columnas sensibles que se guardan como hash
CREATE FUNCTION auditoria.tg_registrar() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    v_ignorar   text[] := string_to_array(coalesce(TG_ARGV[0], ''), ',');
    v_sensibles text[] := string_to_array(coalesce(TG_ARGV[1], ''), ',');
    v_antes     jsonb;
    v_despues   jsonb;
    v_cambios   jsonb;
BEGIN
    v_ignorar := v_ignorar || ARRAY['version', 'actualizado_en'];

    IF TG_OP IN ('UPDATE', 'DELETE') THEN v_antes   := to_jsonb(OLD); END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN v_despues := to_jsonb(NEW); END IF;

    IF TG_OP = 'UPDATE' THEN
        SELECT jsonb_object_agg(
                   n.key,
                   CASE WHEN n.key = ANY (v_sensibles)
                        THEN jsonb_build_object('antes', auditoria.hash_valor(o.value), 'despues', auditoria.hash_valor(n.value))
                        ELSE jsonb_build_object('antes', o.value, 'despues', n.value) END)
        INTO v_cambios
        FROM jsonb_each(v_despues) n
        JOIN jsonb_each(v_antes) o USING (key)
        WHERE n.value IS DISTINCT FROM o.value
          AND NOT (n.key = ANY (v_ignorar));

        IF v_cambios IS NULL THEN          -- nada relevante cambió
            RETURN NULL;
        END IF;
    END IF;

    INSERT INTO auditoria.registro (tabla, operacion, registro_id, usuario_id, antes, despues, cambios)
    VALUES (TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME,
            TG_OP,
            coalesce(v_despues, v_antes) ->> 'id' ,
            nullif(current_setting('rumbo.usuario_id', true), '')::bigint,
            auditoria.enmascarar(v_antes,   v_sensibles),
            auditoria.enmascarar(v_despues, v_sensibles),
            v_cambios);
    RETURN NULL;
END $$;

-- La auditoría no se modifica ni se borra (ni siquiera el dueño sin desactivar triggers,
-- y eso queda en el log de PostgreSQL porque log_statement = 'ddl').
CREATE FUNCTION auditoria.tg_inmutable() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    RAISE EXCEPTION 'auditoria.registro es inmutable (%)', TG_OP USING ERRCODE = 'RB403';
END $$;

CREATE TRIGGER registro_inmutable    BEFORE UPDATE OR DELETE ON auditoria.registro FOR EACH ROW       EXECUTE FUNCTION auditoria.tg_inmutable();
CREATE TRIGGER registro_sin_truncate BEFORE TRUNCATE         ON auditoria.registro FOR EACH STATEMENT EXECUTE FUNCTION auditoria.tg_inmutable();

-- Tablas auditadas
CREATE TRIGGER auditar AFTER INSERT OR UPDATE OR DELETE ON rumbo.usuario
    FOR EACH ROW EXECUTE FUNCTION auditoria.tg_registrar('', 'nombre');
CREATE TRIGGER auditar AFTER INSERT OR UPDATE OR DELETE ON rumbo.asesor
    FOR EACH ROW EXECUTE FUNCTION auditoria.tg_registrar('ultimo_lead_en,estado_desde', '');
CREATE TRIGGER auditar AFTER INSERT OR UPDATE OR DELETE ON rumbo.lead
    FOR EACH ROW EXECUTE FUNCTION auditoria.tg_registrar('ultimo_mensaje_en', 'telefono,nombre_perfil,datos');
CREATE TRIGGER auditar AFTER INSERT OR UPDATE OR DELETE ON rumbo.venta
    FOR EACH ROW EXECUTE FUNCTION auditoria.tg_registrar('', '');
CREATE TRIGGER auditar AFTER INSERT OR UPDATE OR DELETE ON rumbo.configuracion
    FOR EACH ROW EXECUTE FUNCTION auditoria.tg_registrar('', '');
CREATE TRIGGER auditar AFTER INSERT OR UPDATE OR DELETE ON rumbo.numero_whatsapp
    FOR EACH ROW EXECUTE FUNCTION auditoria.tg_registrar('', '');
CREATE TRIGGER auditar AFTER INSERT OR UPDATE OR DELETE ON rumbo.etapa
    FOR EACH ROW EXECUTE FUNCTION auditoria.tg_registrar('', '');
CREATE TRIGGER auditar AFTER INSERT OR UPDATE OR DELETE ON rumbo.etapa_transicion
    FOR EACH ROW EXECUTE FUNCTION auditoria.tg_registrar('', '');
CREATE TRIGGER auditar AFTER INSERT OR UPDATE OR DELETE ON rumbo.resultado_llamada
    FOR EACH ROW EXECUTE FUNCTION auditoria.tg_registrar('', '');
CREATE TRIGGER auditar AFTER INSERT OR UPDATE OR DELETE ON rumbo.motivo_descarte
    FOR EACH ROW EXECUTE FUNCTION auditoria.tg_registrar('', '');
