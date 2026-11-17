-- 008 · API de solo lectura para CALLFLOW (RF-35, comisiones)
-- CALLFLOW se conecta con el rol rumbo_callflow y SOLO ve estas vistas: nada de teléfonos,
-- nombres de clientes, mensajes ni notas. Las vistas corren como su dueño (rumbo_owner),
-- así CALLFLOW no necesita ningún permiso sobre las tablas.
-- Sincronización incremental: WHERE actualizado_en > :ultima_sincronizacion ORDER BY actualizado_en, venta_id

CREATE VIEW api.ventas WITH (security_barrier) AS
SELECT v.id               AS venta_id,
       v.asesor_id,
       a.codigo_callflow  AS asesor_codigo_callflow,
       v.tipo_visa,
       v.pais,
       v.valor,
       v.moneda,
       v.cerrada_en,
       v.anulada_en,                  -- si no es NULL, CALLFLOW revierte la comisión
       v.actualizado_en
FROM rumbo.venta v
JOIN rumbo.asesor a ON a.id = v.asesor_id;

CREATE VIEW api.asesores WITH (security_barrier) AS
SELECT a.id              AS asesor_id,
       a.codigo_callflow,
       u.nombre,
       u.activo,
       a.actualizado_en
FROM rumbo.asesor a
JOIN rumbo.usuario u ON u.id = a.usuario_id;

COMMENT ON VIEW api.ventas   IS 'Ventas de visas para el cálculo de comisiones en CALLFLOW. Solo lectura.';
COMMENT ON VIEW api.asesores IS 'Asesores de Rumbo y su código de empleado en CALLFLOW. Solo lectura.';
