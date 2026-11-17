-- 009 · Permisos por rol (mínimo privilegio)
--   rumbo_app       → Django y Celery. Lee con RLS; escribe solo columnas libres y vía funciones.
--   rumbo_callflow  → solo las vistas de api, solo lectura.
--   rumbo_migrator  → aplica migraciones (entra como rumbo_owner).
-- Nadie más tiene acceso: PUBLIC no ve los esquemas.

GRANT USAGE ON SCHEMA rumbo, auditoria TO rumbo_app;
GRANT USAGE ON SCHEMA api TO rumbo_callflow;

-- Lectura (filtrada por RLS)
GRANT SELECT ON ALL TABLES IN SCHEMA rumbo TO rumbo_app;
GRANT SELECT ON auditoria.registro TO rumbo_app;

-- Escritura directa permitida (todo lo demás pasa por funciones)
GRANT UPDATE (nombre_perfil, datos, consentimiento_en) ON rumbo.lead TO rumbo_app;
GRANT INSERT (lead_id, autor_usuario_id, texto)        ON rumbo.nota_lead TO rumbo_app;
GRANT UPDATE (estado_entrega)                           ON rumbo.mensaje_whatsapp TO rumbo_app;
-- Administración (RLS limita a rol admin)
GRANT INSERT, UPDATE ON rumbo.usuario TO rumbo_app;
GRANT INSERT, UPDATE (usuario_id, numero_whatsapp_id, codigo_callflow, preferencias) ON rumbo.asesor TO rumbo_app;
GRANT INSERT, UPDATE ON rumbo.numero_whatsapp, rumbo.configuracion,
                        rumbo.etapa, rumbo.etapa_transicion, rumbo.resultado_llamada, rumbo.motivo_descarte TO rumbo_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA rumbo TO rumbo_app;

-- Funciones públicas (cada una valida el rol del contexto)
GRANT EXECUTE ON FUNCTION
    rumbo.ctx_usuario_id(),
    rumbo.ctx_rol(),
    rumbo.ctx_asesor_id(),
    rumbo.en_horario(timestamptz),
    rumbo.recibir_evento_webhook(text, boolean, jsonb),
    rumbo.tomar_eventos_webhook(integer),
    rumbo.marcar_evento_webhook(bigint, text),
    rumbo.registrar_mensaje_entrante(text, text, text, smallint, text, text, jsonb, timestamptz),
    rumbo.registrar_mensaje_saliente(bigint, text, text, text),
    rumbo.registrar_intento(bigint, integer, text, text, timestamptz, jsonb),
    rumbo.cambiar_etapa(bigint, integer, text, text),
    rumbo.reasignar_manual(bigint, bigint),
    rumbo.cambiar_estado_asesor(rumbo.estado_asesor, bigint),
    rumbo.anular_venta(bigint, text),
    rumbo.reasignar_sin_primera_llamada(),
    rumbo.liberar_cola(),
    rumbo.anonimizar_lead(bigint)
TO rumbo_app;
-- Las funciones internas (_repartir, _tomar_lead, _exigir_rol, _bloquear_reparto, config_int)
-- no se otorgan: solo las llaman otras funciones.

-- CALLFLOW
GRANT SELECT ON api.ventas, api.asesores TO rumbo_callflow;
