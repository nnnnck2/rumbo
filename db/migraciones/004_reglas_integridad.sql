-- 004 · Reglas de integridad que no caben en un CHECK
-- Todas las funciones de trigger fijan search_path para que nadie pueda secuestrarlas
-- creando objetos con el mismo nombre en otro esquema.

-- ── Versión y marcas de tiempo (bloqueo optimista) ──────────────────────────────
-- La app actualiza con  ... WHERE id = $1 AND version = $2 ; si afecta 0 filas, otro
-- usuario cambió el registro primero. La app no puede fijar la versión a mano.
CREATE FUNCTION rumbo.tg_versionar() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, rumbo AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.version        := 1;
        NEW.creado_en      := now();
        NEW.actualizado_en := now();
    ELSE
        NEW.version        := OLD.version + 1;
        NEW.creado_en      := OLD.creado_en;
        NEW.actualizado_en := now();
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER usuario_versionar       BEFORE INSERT OR UPDATE ON rumbo.usuario       FOR EACH ROW EXECUTE FUNCTION rumbo.tg_versionar();
CREATE TRIGGER asesor_versionar        BEFORE INSERT OR UPDATE ON rumbo.asesor        FOR EACH ROW EXECUTE FUNCTION rumbo.tg_versionar();
CREATE TRIGGER lead_versionar          BEFORE INSERT OR UPDATE ON rumbo.lead          FOR EACH ROW EXECUTE FUNCTION rumbo.tg_versionar();
CREATE TRIGGER venta_versionar         BEFORE INSERT OR UPDATE ON rumbo.venta         FOR EACH ROW EXECUTE FUNCTION rumbo.tg_versionar();
CREATE TRIGGER configuracion_versionar BEFORE INSERT OR UPDATE ON rumbo.configuracion FOR EACH ROW EXECUTE FUNCTION rumbo.tg_versionar();

-- ── Tablas de solo inserción (historiales) ──────────────────────────────────────
CREATE FUNCTION rumbo.tg_solo_insercion() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, rumbo AS $$
BEGIN
    RAISE EXCEPTION 'La tabla %.% es de solo inserción: no se permite %',
        TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'RB403';
END $$;

CREATE TRIGGER nota_lead_inmutable   BEFORE UPDATE OR DELETE ON rumbo.nota_lead            FOR EACH ROW EXECUTE FUNCTION rumbo.tg_solo_insercion();
CREATE TRIGGER etapa_hist_inmutable  BEFORE UPDATE OR DELETE ON rumbo.lead_etapa_historial FOR EACH ROW EXECUTE FUNCTION rumbo.tg_solo_insercion();
CREATE TRIGGER asignacion_inmutable  BEFORE UPDATE OR DELETE ON rumbo.asignacion           FOR EACH ROW EXECUTE FUNCTION rumbo.tg_solo_insercion();
CREATE TRIGGER intento_inmutable     BEFORE UPDATE OR DELETE ON rumbo.intento_llamada      FOR EACH ROW EXECUTE FUNCTION rumbo.tg_solo_insercion();
-- Leads, mensajes y ventas nunca se borran (se anonimizan o se anulan).
CREATE TRIGGER lead_sin_borrado      BEFORE DELETE ON rumbo.lead             FOR EACH ROW EXECUTE FUNCTION rumbo.tg_solo_insercion();
CREATE TRIGGER mensaje_sin_borrado   BEFORE DELETE ON rumbo.mensaje_whatsapp FOR EACH ROW EXECUTE FUNCTION rumbo.tg_solo_insercion();
CREATE TRIGGER venta_sin_borrado     BEFORE DELETE ON rumbo.venta            FOR EACH ROW EXECUTE FUNCTION rumbo.tg_solo_insercion();

-- TRUNCATE salta los triggers de fila: se bloquea aparte.
CREATE FUNCTION rumbo.tg_sin_truncate() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, rumbo AS $$
BEGIN
    RAISE EXCEPTION 'TRUNCATE no permitido en %.%', TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = 'RB403';
END $$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['usuario','asesor','lead','nota_lead','lead_etapa_historial','asignacion',
                             'intento_llamada','mensaje_whatsapp','webhook_evento','venta','configuracion']
    LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON rumbo.%I FOR EACH STATEMENT EXECUTE FUNCTION rumbo.tg_sin_truncate()',
                       t || '_sin_truncate', t);
    END LOOP;
END $$;

-- ── Ventas: inmutables salvo la anulación (una sola vez) ────────────────────────
-- Las comisiones se calculan sobre estas filas: corregir una venta = anularla y crear otra.
CREATE FUNCTION rumbo.tg_venta_inmutable() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, rumbo AS $$
BEGIN
    IF (NEW.lead_id, NEW.asesor_id, NEW.tipo_visa, NEW.pais, NEW.valor, NEW.moneda, NEW.cerrada_en, NEW.registrada_por_usuario_id)
       IS DISTINCT FROM
       (OLD.lead_id, OLD.asesor_id, OLD.tipo_visa, OLD.pais, OLD.valor, OLD.moneda, OLD.cerrada_en, OLD.registrada_por_usuario_id)
    THEN
        RAISE EXCEPTION 'Una venta registrada no se modifica: anúlela y registre otra' USING ERRCODE = 'RB403';
    END IF;
    IF OLD.anulada_en IS NOT NULL THEN
        RAISE EXCEPTION 'La venta % ya está anulada', OLD.id USING ERRCODE = 'RB403';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER venta_inmutable BEFORE UPDATE ON rumbo.venta FOR EACH ROW EXECUTE FUNCTION rumbo.tg_venta_inmutable();

-- ── El usuario de un asesor debe tener rol asesor ───────────────────────────────
CREATE FUNCTION rumbo.tg_asesor_rol() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, rumbo AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM rumbo.usuario u WHERE u.id = NEW.usuario_id AND u.rol = 'asesor') THEN
        RAISE EXCEPTION 'El usuario % no tiene rol asesor', NEW.usuario_id USING ERRCODE = 'RB422';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.estado IS DISTINCT FROM OLD.estado THEN
        NEW.estado_desde := now();
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER asesor_rol BEFORE INSERT OR UPDATE ON rumbo.asesor FOR EACH ROW EXECUTE FUNCTION rumbo.tg_asesor_rol();

-- No se puede cambiar el rol de un usuario que tiene ficha de asesor.
CREATE FUNCTION rumbo.tg_usuario_rol() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, rumbo AS $$
BEGIN
    IF NEW.rol <> 'asesor' AND EXISTS (SELECT 1 FROM rumbo.asesor a WHERE a.usuario_id = NEW.id) THEN
        RAISE EXCEPTION 'El usuario % es asesor: no puede cambiar a rol %', NEW.id, NEW.rol USING ERRCODE = 'RB422';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER usuario_rol BEFORE UPDATE OF rol ON rumbo.usuario FOR EACH ROW EXECUTE FUNCTION rumbo.tg_usuario_rol();

-- ── Máquina de estados del lead ─────────────────────────────────────────────────
CREATE FUNCTION rumbo.tg_lead_estado() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v_final boolean;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.etapa_codigo IS DISTINCT FROM OLD.etapa_codigo THEN
        IF NOT EXISTS (
            SELECT 1
            FROM rumbo.etapa_transicion t
            JOIN rumbo.etapa e ON e.codigo = t.hacia
            WHERE t.desde = OLD.etapa_codigo AND t.hacia = NEW.etapa_codigo AND e.activo
        ) THEN
            RAISE EXCEPTION 'Transición de etapa no permitida: % → %', OLD.etapa_codigo, NEW.etapa_codigo
                USING ERRCODE = 'RB422';
        END IF;
    END IF;

    SELECT e.es_final INTO v_final FROM rumbo.etapa e WHERE e.codigo = NEW.etapa_codigo;

    IF v_final THEN
        NEW.estado_asignacion := 'cerrado';
        NEW.cerrado_en        := coalesce(NEW.cerrado_en, now());
        NEW.proxima_accion_en := NULL;
        IF NEW.etapa_codigo <> 'descartado' THEN
            NEW.motivo_descarte_codigo := NULL;
        END IF;
    ELSE
        IF NEW.estado_asignacion = 'cerrado' THEN          -- reapertura
            IF NEW.asesor_id IS NULL THEN
                NEW.estado_asignacion := 'en_cola';
            ELSE
                NEW.estado_asignacion := 'asignado';
                NEW.asignado_en       := coalesce(NEW.asignado_en, now());
            END IF;
        END IF;
        NEW.cerrado_en             := NULL;
        NEW.motivo_descarte_codigo := NULL;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER lead_estado BEFORE INSERT OR UPDATE ON rumbo.lead FOR EACH ROW EXECUTE FUNCTION rumbo.tg_lead_estado();

-- Historial de etapas (trazabilidad de estados).
CREATE FUNCTION rumbo.tg_lead_etapa_historial() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    IF TG_OP = 'INSERT' OR NEW.etapa_codigo IS DISTINCT FROM OLD.etapa_codigo THEN
        INSERT INTO rumbo.lead_etapa_historial (lead_id, desde, hacia, usuario_id)
        VALUES (NEW.id,
                CASE WHEN TG_OP = 'UPDATE' THEN OLD.etapa_codigo END,
                NEW.etapa_codigo,
                nullif(current_setting('rumbo.usuario_id', true), '')::bigint);
    END IF;
    RETURN NULL;
END $$;

CREATE TRIGGER lead_etapa_historial AFTER INSERT OR UPDATE OF etapa_codigo ON rumbo.lead
    FOR EACH ROW EXECUTE FUNCTION rumbo.tg_lead_etapa_historial();

-- ── Validación de la configuración (parte jsonb) ────────────────────────────────
CREATE FUNCTION rumbo.tg_validar_configuracion() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, rumbo AS $$
DECLARE
    v jsonb := NEW.valor;
    d jsonb;
BEGIN
    CASE NEW.clave
    WHEN 'horario' THEN
        IF jsonb_typeof(v) <> 'object' OR NOT v ?& ARRAY['inicio', 'fin', 'dias', 'zona'] THEN
            RAISE EXCEPTION 'horario requiere {inicio, fin, dias, zona}';
        END IF;
        IF (v ->> 'inicio')::time >= (v ->> 'fin')::time THEN
            RAISE EXCEPTION 'horario: inicio debe ser menor que fin';
        END IF;
        PERFORM now() AT TIME ZONE (v ->> 'zona');                    -- zona horaria válida
        IF jsonb_typeof(v -> 'dias') <> 'array' OR jsonb_array_length(v -> 'dias') = 0 THEN
            RAISE EXCEPTION 'horario.dias debe ser una lista de días ISO (1 = lunes … 7 = domingo)';
        END IF;
        FOR d IN SELECT * FROM jsonb_array_elements(v -> 'dias') LOOP
            IF jsonb_typeof(d) <> 'number' OR d::int NOT BETWEEN 1 AND 7 THEN
                RAISE EXCEPTION 'horario.dias contiene un día inválido: %', d;
            END IF;
        END LOOP;
    WHEN 'max_intentos_por_asesor' THEN
        IF jsonb_typeof(v) <> 'number' OR v::int NOT BETWEEN 1 AND 10 THEN
            RAISE EXCEPTION 'max_intentos_por_asesor debe ser un número entre 1 y 10';
        END IF;
    WHEN 'minutos_primera_llamada' THEN
        IF jsonb_typeof(v) <> 'number' OR v::int NOT BETWEEN 1 AND 240 THEN
            RAISE EXCEPTION 'minutos_primera_llamada debe ser un número entre 1 y 240';
        END IF;
    WHEN 'minutos_entre_reintentos' THEN
        IF jsonb_typeof(v) <> 'number' OR v::int NOT BETWEEN 1 AND 1440 THEN
            RAISE EXCEPTION 'minutos_entre_reintentos debe ser un número entre 1 y 1440';
        END IF;
    WHEN 'texto_bienvenida', 'texto_fuera_horario', 'texto_privacidad' THEN
        IF jsonb_typeof(v) <> 'string' OR length(v #>> '{}') NOT BETWEEN 1 AND 1024 THEN
            RAISE EXCEPTION '% debe ser un texto de 1 a 1024 caracteres', NEW.clave;
        END IF;
    ELSE
        RAISE EXCEPTION 'Clave de configuración desconocida: %', NEW.clave;
    END CASE;
    RETURN NEW;
EXCEPTION
    WHEN invalid_datetime_format OR invalid_parameter_value OR invalid_text_representation
      OR datetime_field_overflow OR raise_exception THEN
        RAISE EXCEPTION 'Configuración inválida (%): %', NEW.clave, SQLERRM USING ERRCODE = 'RB422';
END $$;

CREATE TRIGGER configuracion_validar BEFORE INSERT OR UPDATE ON rumbo.configuracion
    FOR EACH ROW EXECUTE FUNCTION rumbo.tg_validar_configuracion();
