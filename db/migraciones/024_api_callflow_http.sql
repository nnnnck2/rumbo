-- 024 · SCRUM-57 (RF-35) · API HTTPS para que CALLFLOW consulte ventas cerradas y asesores
--   CALLFLOW llama a https://<dominio>/api/callflow/v1/… con un token (CALLFLOW → nube; CALLFLOW nunca recibe
--   conexiones). Django lee con estas funciones, que devuelven lo mismo que las vistas api.ventas y
--   api.asesores de 008 (sin teléfonos, nombres de clientes, mensajes ni notas).
--   · Solo el rol 'sistema' (el contexto que usa la API después de validar el token).
--   · Sincronización incremental por (actualizado_en, venta_id): una venta anulada cambia su actualizado_en
--     y vuelve a salir, así CALLFLOW revierte la comisión.

CREATE FUNCTION api.callflow_ventas(p_desde timestamptz DEFAULT NULL, p_despues_id bigint DEFAULT NULL,
                                    p_limite integer DEFAULT 500)
RETURNS SETOF api.ventas
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, api, rumbo AS $$
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    RETURN QUERY
    SELECT v.* FROM api.ventas v
    WHERE p_desde IS NULL
       OR v.actualizado_en > p_desde
       OR (v.actualizado_en = p_desde AND v.venta_id > coalesce(p_despues_id, 0))
    ORDER BY v.actualizado_en, v.venta_id
    LIMIT least(greatest(coalesce(p_limite, 500), 1), 1000);
END $$;

CREATE FUNCTION api.callflow_asesores()
RETURNS SETOF api.asesores
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, api, rumbo AS $$
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    RETURN QUERY SELECT a.* FROM api.asesores a ORDER BY a.asesor_id;
END $$;

GRANT USAGE ON SCHEMA api TO rumbo_app;
REVOKE ALL ON FUNCTION api.callflow_ventas(timestamptz, bigint, integer), api.callflow_asesores() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.callflow_ventas(timestamptz, bigint, integer), api.callflow_asesores() TO rumbo_app;
