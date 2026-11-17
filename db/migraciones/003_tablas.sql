-- 003 · Tablas del negocio
-- Convenciones:
--   · PK bigint IDENTITY (GENERATED ALWAYS: nadie puede forzar ids a mano).
--   · Toda restricción de negocio que se pueda expresar como CHECK/FK/UNIQUE vive aquí,
--     no en Django: la base rechaza datos inválidos aunque la app tenga un bug.
--   · Columnas `version` = bloqueo optimista (la incrementa un trigger, ver 004).
--   · Modelado híbrido: columnas relacionales para lo que se filtra/une y `jsonb`
--     validado para lo que cambia según la campaña (datos del lead, preferencias, payloads).

CREATE TYPE rumbo.rol_usuario       AS ENUM ('asesor', 'supervisor', 'admin', 'sistema');
CREATE TYPE rumbo.estado_asesor     AS ENUM ('disponible', 'ocupado', 'pausa', 'fuera_turno');
CREATE TYPE rumbo.estado_asignacion AS ENUM ('en_cola', 'asignado', 'cerrado');
CREATE TYPE rumbo.motivo_asignacion AS ENUM (
    'reparto',               -- lead nuevo, round robin
    'reintentos_agotados',   -- el asesor hizo los 3 intentos sin contacto
    'sin_primera_llamada',   -- el asesor no llamó dentro del tiempo máximo
    'asesor_inactivo',       -- el asesor dueño del lead ya no está activo
    'cola_horario',          -- el lead llegó fuera de horario y se repartió al abrir
    'manual'                 -- reasignación por supervisor
);

-- Dominio de teléfonos en formato E.164 (+593...)
CREATE DOMAIN rumbo.telefono_e164 AS text
    CHECK (VALUE ~ '^\+[1-9][0-9]{7,14}$');

-- ─────────────────────────────── Usuarios y asesores ───────────────────────────────

-- Un registro por usuario de Django (id = auth_user.id). El id 0 es el usuario "sistema"
-- que usan los workers de Celery.
CREATE TABLE rumbo.usuario (
    id              bigint      PRIMARY KEY CHECK (id >= 0),
    nombre          text        NOT NULL CHECK (length(btrim(nombre)) BETWEEN 1 AND 120),
    rol             rumbo.rol_usuario NOT NULL,
    activo          boolean     NOT NULL DEFAULT true,
    version         integer     NOT NULL DEFAULT 1,
    creado_en       timestamptz NOT NULL DEFAULT now(),
    actualizado_en  timestamptz NOT NULL DEFAULT now(),
    CHECK ((id = 0) = (rol = 'sistema'))
);

CREATE TABLE rumbo.numero_whatsapp (
    id                    smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    telefono              rumbo.telefono_e164 NOT NULL UNIQUE,
    meta_phone_number_id  text     UNIQUE CHECK (meta_phone_number_id ~ '^[0-9]{5,30}$'),
    conectado_api         boolean  NOT NULL DEFAULT false,
    activo                boolean  NOT NULL DEFAULT true,
    creado_en             timestamptz NOT NULL DEFAULT now(),
    CHECK (NOT conectado_api OR meta_phone_number_id IS NOT NULL)
);

CREATE TABLE rumbo.asesor (
    id                  bigint   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id          bigint   NOT NULL UNIQUE REFERENCES rumbo.usuario (id),
    numero_whatsapp_id  smallint REFERENCES rumbo.numero_whatsapp (id),
    codigo_callflow     text     UNIQUE CHECK (length(btrim(codigo_callflow)) BETWEEN 1 AND 40),
    estado              rumbo.estado_asesor NOT NULL DEFAULT 'fuera_turno',
    estado_desde        timestamptz NOT NULL DEFAULT now(),
    ultimo_lead_en      timestamptz,   -- puntero del round robin
    preferencias        jsonb    NOT NULL DEFAULT '{}'
                        CHECK (jsonb_typeof(preferencias) = 'object' AND pg_column_size(preferencias) < 4096),
    version             integer  NOT NULL DEFAULT 1,
    creado_en           timestamptz NOT NULL DEFAULT now(),
    actualizado_en      timestamptz NOT NULL DEFAULT now()
);

-- ─────────────────────────────── Leads ───────────────────────────────

CREATE TABLE rumbo.lead (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    telefono                rumbo.telefono_e164 NOT NULL,
    nombre_perfil           text   CHECK (length(nombre_perfil) <= 200),
    numero_whatsapp_id      smallint REFERENCES rumbo.numero_whatsapp (id),  -- número por el que escribió
    origen                  text   NOT NULL DEFAULT 'whatsapp'
                            CHECK (origen IN ('whatsapp', 'manual', 'referido', 'otro')),
    etapa_codigo            text   NOT NULL DEFAULT 'nuevo' REFERENCES rumbo.etapa (codigo) ON UPDATE CASCADE,
    motivo_descarte_codigo  text   REFERENCES rumbo.motivo_descarte (codigo) ON UPDATE CASCADE,
    estado_asignacion       rumbo.estado_asignacion NOT NULL DEFAULT 'en_cola',
    asesor_id               bigint REFERENCES rumbo.asesor (id),
    asignado_en             timestamptz,
    intentos_asesor_actual  smallint NOT NULL DEFAULT 0 CHECK (intentos_asesor_actual >= 0),
    intentos_totales        integer  NOT NULL DEFAULT 0 CHECK (intentos_totales >= 0),
    proxima_accion_en       timestamptz,

    -- Parte flexible: tipo de visa, país, datos de la campaña/anuncio de Meta, etc.
    datos                   jsonb  NOT NULL DEFAULT '{}',
    -- Columnas generadas desde el jsonb para filtrar e indexar sin perder flexibilidad.
    tipo_visa               text   GENERATED ALWAYS AS (datos ->> 'tipo_visa') STORED,
    pais_interes            text   GENERATED ALWAYS AS (datos ->> 'pais_interes') STORED,

    consentimiento_en       timestamptz,              -- LOPDP
    anonimizado_en          timestamptz,              -- derecho de supresión (LOPDP)
    primer_contacto_en      timestamptz NOT NULL DEFAULT now(),
    ultimo_mensaje_en       timestamptz,
    cerrado_en              timestamptz,
    version                 integer NOT NULL DEFAULT 1,
    creado_en               timestamptz NOT NULL DEFAULT now(),
    actualizado_en          timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT lead_telefono_uk UNIQUE (telefono),
    CONSTRAINT lead_datos_ck CHECK (
        jsonb_typeof(datos) = 'object'
        AND pg_column_size(datos) < 16384
        AND (NOT datos ? 'tipo_visa'    OR jsonb_typeof(datos -> 'tipo_visa')    = 'string')
        AND (NOT datos ? 'pais_interes' OR jsonb_typeof(datos -> 'pais_interes') = 'string')
    ),
    CONSTRAINT lead_asignado_ck  CHECK (estado_asignacion <> 'asignado' OR (asesor_id IS NOT NULL AND asignado_en IS NOT NULL)),
    CONSTRAINT lead_en_cola_ck   CHECK (estado_asignacion <> 'en_cola'  OR asesor_id IS NULL),
    CONSTRAINT lead_cerrado_ck   CHECK ((estado_asignacion = 'cerrado') = (cerrado_en IS NOT NULL)),
    CONSTRAINT lead_descarte_ck  CHECK ((etapa_codigo = 'descartado') = (motivo_descarte_codigo IS NOT NULL))
) WITH (fillfactor = 90);   -- deja espacio en cada página para actualizaciones HOT

-- Notas internas del asesor (RF-26). Solo inserción.
CREATE TABLE rumbo.nota_lead (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lead_id           bigint NOT NULL REFERENCES rumbo.lead (id),
    autor_usuario_id  bigint NOT NULL REFERENCES rumbo.usuario (id),
    texto             text   NOT NULL CHECK (length(btrim(texto)) BETWEEN 1 AND 4000),
    creado_en         timestamptz NOT NULL DEFAULT now()
);

-- Historial de etapas (lo llena un trigger, ver 004). Solo inserción.
CREATE TABLE rumbo.lead_etapa_historial (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lead_id     bigint NOT NULL REFERENCES rumbo.lead (id),
    desde       text   REFERENCES rumbo.etapa (codigo) ON UPDATE CASCADE,
    hacia       text   NOT NULL REFERENCES rumbo.etapa (codigo) ON UPDATE CASCADE,
    usuario_id  bigint REFERENCES rumbo.usuario (id),
    creado_en   timestamptz NOT NULL DEFAULT now()
);

-- Historial de asignaciones (round robin, reintentos, manual). Solo inserción.
CREATE TABLE rumbo.asignacion (
    id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lead_id                  bigint NOT NULL REFERENCES rumbo.lead (id),
    asesor_anterior_id       bigint REFERENCES rumbo.asesor (id),
    asesor_id                bigint NOT NULL REFERENCES rumbo.asesor (id),
    motivo                   rumbo.motivo_asignacion NOT NULL,
    asignado_por_usuario_id  bigint REFERENCES rumbo.usuario (id),
    creado_en                timestamptz NOT NULL DEFAULT now()
);

-- Cada intento de llamada (RF-22). Solo inserción.
CREATE TABLE rumbo.intento_llamada (
    id                         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lead_id                    bigint   NOT NULL REFERENCES rumbo.lead (id),
    asesor_id                  bigint   NOT NULL REFERENCES rumbo.asesor (id),
    numero                     integer  NOT NULL CHECK (numero >= 1),
    resultado_codigo           text     NOT NULL REFERENCES rumbo.resultado_llamada (codigo) ON UPDATE CASCADE,
    nota                       text     CHECK (length(nota) <= 2000),
    agendado_para              timestamptz,
    registrado_por_usuario_id  bigint   NOT NULL REFERENCES rumbo.usuario (id),
    creado_en                  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT intento_numero_uk UNIQUE (lead_id, numero)
);

-- ─────────────────────────────── WhatsApp ───────────────────────────────

CREATE TABLE rumbo.mensaje_whatsapp (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lead_id                bigint   NOT NULL REFERENCES rumbo.lead (id),
    numero_whatsapp_id     smallint NOT NULL REFERENCES rumbo.numero_whatsapp (id),
    wa_message_id          text     NOT NULL CHECK (length(wa_message_id) BETWEEN 1 AND 255),
    direccion              text     NOT NULL CHECK (direccion IN ('entrante', 'saliente')),
    tipo                   text     NOT NULL DEFAULT 'text' CHECK (tipo ~ '^[a-z_]{1,30}$'),
    cuerpo                 text     CHECK (length(cuerpo) <= 4096),
    enviado_por_asesor_id  bigint   REFERENCES rumbo.asesor (id),
    estado_entrega         text     CHECK (estado_entrega IN ('enviado', 'entregado', 'leido', 'fallido')),
    payload                jsonb    NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(payload) = 'object'),
    ocurrido_en            timestamptz NOT NULL,
    creado_en              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT mensaje_wa_id_uk UNIQUE (wa_message_id),   -- idempotencia: Meta reenvía webhooks
    CHECK (direccion = 'saliente' OR enviado_por_asesor_id IS NULL)
);

-- Bandeja de entrada del webhook: se guarda el evento crudo antes de procesarlo, así
-- un fallo del worker nunca pierde un mensaje (patrón inbox).
CREATE TABLE rumbo.webhook_evento (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    idempotencia  text     NOT NULL UNIQUE CHECK (length(idempotencia) BETWEEN 8 AND 128),
    firma_valida  boolean  NOT NULL,
    payload       jsonb    NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    recibido_en   timestamptz NOT NULL DEFAULT now(),
    procesado_en  timestamptz,
    intentos      smallint NOT NULL DEFAULT 0 CHECK (intentos >= 0),
    ultimo_error  text     CHECK (length(ultimo_error) <= 2000)
);

-- ─────────────────────────────── Ventas (comisiones vía CALLFLOW) ───────────────────────────────

CREATE TABLE rumbo.venta (
    id                         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lead_id                    bigint        NOT NULL REFERENCES rumbo.lead (id),
    asesor_id                  bigint        NOT NULL REFERENCES rumbo.asesor (id),
    tipo_visa                  text          NOT NULL CHECK (length(btrim(tipo_visa)) BETWEEN 1 AND 80),
    pais                       text          CHECK (length(btrim(pais)) BETWEEN 1 AND 80),
    valor                      numeric(12,2) NOT NULL CHECK (valor > 0),
    moneda                     char(3)       NOT NULL DEFAULT 'USD' CHECK (moneda ~ '^[A-Z]{3}$'),
    cerrada_en                 timestamptz   NOT NULL DEFAULT now(),
    registrada_por_usuario_id  bigint        NOT NULL REFERENCES rumbo.usuario (id),
    anulada_en                 timestamptz,
    motivo_anulacion           text          CHECK (length(btrim(motivo_anulacion)) BETWEEN 3 AND 500),
    version                    integer       NOT NULL DEFAULT 1,
    creado_en                  timestamptz   NOT NULL DEFAULT now(),
    actualizado_en             timestamptz   NOT NULL DEFAULT now(),
    CHECK ((anulada_en IS NULL) = (motivo_anulacion IS NULL))
);

-- ─────────────────────────────── Configuración ───────────────────────────────

CREATE TABLE rumbo.configuracion (
    clave                       text  PRIMARY KEY CHECK (clave ~ '^[a-z][a-z_]{1,59}$'),
    valor                       jsonb NOT NULL,
    descripcion                 text,
    actualizado_por_usuario_id  bigint REFERENCES rumbo.usuario (id),
    version                     integer     NOT NULL DEFAULT 1,
    creado_en                   timestamptz NOT NULL DEFAULT now(),
    actualizado_en              timestamptz NOT NULL DEFAULT now()
);

-- ─────────────────────────────── Índices ───────────────────────────────
-- Pensados para las consultas reales: lista de llamadas del asesor, cola de fuera de
-- horario, vencidos para reasignar, ficha del lead, sincronización con CALLFLOW.

-- Lista de llamadas del asesor (RF-20): solo leads asignados.
CREATE INDEX lead_lista_asesor_ix   ON rumbo.lead (asesor_id, proxima_accion_en)
    WHERE estado_asignacion = 'asignado';
-- Cola de fuera de horario (RF-13), en orden de llegada.
CREATE INDEX lead_cola_ix           ON rumbo.lead (primer_contacto_en)
    WHERE estado_asignacion = 'en_cola';
-- Búsqueda por etapa y por fecha para reportes.
CREATE INDEX lead_etapa_ix          ON rumbo.lead (etapa_codigo, creado_en);
-- Búsqueda por nombre aproximado.
CREATE INDEX lead_nombre_trgm_ix    ON rumbo.lead USING gin (nombre_perfil gin_trgm_ops);
-- Consultas sobre la parte flexible (datos @> '{"campania": "X"}').
CREATE INDEX lead_datos_gin_ix      ON rumbo.lead USING gin (datos jsonb_path_ops);
CREATE INDEX lead_tipo_visa_ix      ON rumbo.lead (tipo_visa) WHERE tipo_visa IS NOT NULL;

CREATE INDEX asesor_reparto_ix      ON rumbo.asesor (estado, ultimo_lead_en);

CREATE INDEX nota_lead_ix           ON rumbo.nota_lead (lead_id, creado_en);
CREATE INDEX etapa_hist_lead_ix     ON rumbo.lead_etapa_historial (lead_id, creado_en);
CREATE INDEX asignacion_lead_ix     ON rumbo.asignacion (lead_id, creado_en);
CREATE INDEX asignacion_asesor_ix   ON rumbo.asignacion (asesor_id, creado_en);
CREATE INDEX intento_lead_ix        ON rumbo.intento_llamada (lead_id, creado_en);
CREATE INDEX intento_asesor_ix      ON rumbo.intento_llamada (asesor_id, creado_en);
CREATE INDEX mensaje_lead_ix        ON rumbo.mensaje_whatsapp (lead_id, ocurrido_en DESC);
CREATE INDEX webhook_pendiente_ix   ON rumbo.webhook_evento (id)
    WHERE procesado_en IS NULL AND firma_valida;
CREATE INDEX venta_asesor_ix        ON rumbo.venta (asesor_id, cerrada_en);
CREATE INDEX venta_lead_ix          ON rumbo.venta (lead_id);
CREATE INDEX venta_sync_ix          ON rumbo.venta (actualizado_en, id);   -- sync incremental de CALLFLOW
