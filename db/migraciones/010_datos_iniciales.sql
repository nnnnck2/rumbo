-- 010 · Datos iniciales
-- ⚠ Valores pendientes de confirmar con el área (SCRUM-7):
--     días de atención, minutos_primera_llamada, minutos_entre_reintentos.

INSERT INTO rumbo.usuario (id, nombre, rol) VALUES (0, 'Sistema (workers)', 'sistema');

INSERT INTO rumbo.numero_whatsapp (telefono) VALUES
    ('+593961319535'),
    ('+593983154285');

INSERT INTO rumbo.configuracion (clave, valor, descripcion) VALUES
    ('horario',
     '{"inicio": "09:00", "fin": "18:00", "dias": [1, 2, 3, 4, 5], "zona": "America/Guayaquil"}',
     'Horario de atención (SCRUM-7: 9:00 a 18:00). Días ISO: 1 = lunes … 7 = domingo.'),
    ('max_intentos_por_asesor',  '3',  'Intentos sin contacto antes de pasar el lead al siguiente asesor (SCRUM-7).'),
    ('minutos_primera_llamada',  '15', 'PENDIENTE con el área: minutos máximos para la primera llamada.'),
    ('minutos_entre_reintentos', '30', 'PENDIENTE con el área: espera entre reintentos.'),
    ('texto_bienvenida',
     '"¡Hola, te saluda Multivisa! ¿Cómo podemos ayudarlo?"',
     'Respuesta automática al primer mensaje (SCRUM-7).'),
    ('texto_fuera_horario',
     '"¡Hola, te saluda Multivisa! Nuestro horario es de lunes a viernes de 9:00 a 18:00. Un asesor te contactará en cuanto abramos."',
     'Respuesta fuera de horario.');
