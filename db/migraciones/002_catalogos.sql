-- 002 · Catálogos configurables (etapas, resultados de llamada, motivos de descarte)
-- Son tablas y no ENUM para que el área pueda ajustarlos sin migraciones.
-- ⚠ Valores iniciales tomados de la propuesta v0.2: pendientes de validar con el área (SCRUM-13).
-- Los códigos 'nuevo', 'cerrado' y 'descartado' son reservados: el sistema depende de ellos.

CREATE TABLE rumbo.etapa (
    codigo    text     PRIMARY KEY CHECK (codigo ~ '^[a-z][a-z_]{1,39}$'),
    nombre    text     NOT NULL CHECK (length(btrim(nombre)) BETWEEN 1 AND 80),
    orden     smallint NOT NULL UNIQUE CHECK (orden > 0),
    es_final  boolean  NOT NULL DEFAULT false,
    activo    boolean  NOT NULL DEFAULT true
);

-- Máquina de estados: solo se permiten las transiciones listadas aquí.
CREATE TABLE rumbo.etapa_transicion (
    desde  text NOT NULL REFERENCES rumbo.etapa (codigo) ON UPDATE CASCADE,
    hacia  text NOT NULL REFERENCES rumbo.etapa (codigo) ON UPDATE CASCADE,
    PRIMARY KEY (desde, hacia),
    CHECK (desde <> hacia)
);

CREATE TABLE rumbo.motivo_descarte (
    codigo  text    PRIMARY KEY CHECK (codigo ~ '^[a-z][a-z_]{1,39}$'),
    nombre  text    NOT NULL CHECK (length(btrim(nombre)) BETWEEN 1 AND 80),
    activo  boolean NOT NULL DEFAULT true
);

CREATE TABLE rumbo.resultado_llamada (
    codigo                  text    PRIMARY KEY CHECK (codigo ~ '^[a-z][a-z_]{1,39}$'),
    nombre                  text    NOT NULL CHECK (length(btrim(nombre)) BETWEEN 1 AND 80),
    cuenta_como_intento     boolean NOT NULL,          -- suma al contador de 3 intentos
    requiere_agenda         boolean NOT NULL DEFAULT false,
    requiere_venta          boolean NOT NULL DEFAULT false,
    etapa_destino           text    REFERENCES rumbo.etapa (codigo) ON UPDATE CASCADE,
    motivo_descarte_codigo  text    REFERENCES rumbo.motivo_descarte (codigo) ON UPDATE CASCADE,
    activo                  boolean NOT NULL DEFAULT true,
    CHECK (NOT (requiere_agenda AND requiere_venta)),
    CHECK (NOT requiere_venta OR etapa_destino = 'cerrado'),
    CHECK ((etapa_destino = 'descartado') = (motivo_descarte_codigo IS NOT NULL))
);

INSERT INTO rumbo.etapa (codigo, nombre, orden, es_final) VALUES
    ('nuevo',         'Nuevo',          1, false),
    ('en_contacto',   'En contacto',    2, false),
    ('en_asesoria',   'En asesoría',    3, false),
    ('documentos',    'Documentos',     4, false),
    ('pago',          'Pago',           5, false),
    ('cita_agendada', 'Cita agendada',  6, false),
    ('cerrado',       'Cerrado (venta)',7, true),
    ('descartado',    'Descartado',     8, true);

-- Transiciones: avanzar a cualquier etapa posterior, cerrar o descartar desde
-- cualquier etapa abierta, y reabrir un descartado.
INSERT INTO rumbo.etapa_transicion (desde, hacia)
SELECT d.codigo, h.codigo
FROM rumbo.etapa d
JOIN rumbo.etapa h ON h.codigo <> d.codigo
WHERE NOT d.es_final
  AND (h.es_final OR h.orden > d.orden);

INSERT INTO rumbo.etapa_transicion (desde, hacia) VALUES ('descartado', 'en_contacto');

INSERT INTO rumbo.motivo_descarte (codigo, nombre) VALUES
    ('precio',          'Precio'),
    ('no_califica',     'No califica'),
    ('ya_tramito',      'Ya tramitó'),
    ('numero_invalido', 'Número inválido'),
    ('no_interesado',   'No interesado'),
    ('otro',            'Otro');

INSERT INTO rumbo.resultado_llamada
    (codigo, nombre, cuenta_como_intento, requiere_agenda, requiere_venta, etapa_destino, motivo_descarte_codigo) VALUES
    ('no_contesta',     'No contesta / buzón',        true,  false, false, NULL,          NULL),
    ('numero_invalido', 'Número inválido',            false, false, false, 'descartado',  'numero_invalido'),
    ('llamar_despues',  'Llamar después',             false, true,  false, 'en_contacto', NULL),
    ('interesado',      'Contactado · interesado',    false, false, false, 'en_asesoria', NULL),
    ('no_interesado',   'Contactado · no interesado', false, false, false, 'descartado',  'no_interesado'),
    ('venta_cerrada',   'Venta cerrada',              false, false, true,  'cerrado',     NULL);
