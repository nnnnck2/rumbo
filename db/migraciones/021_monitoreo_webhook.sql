-- 021 · SCRUM-41 · Monitoreo del webhook de WhatsApp
--   · rumbo.estado_webhook(): cómo está la bandeja del webhook (último mensaje válido, eventos atascados o
--     que agotaron los reintentos, firmas inválidas). La usan la tarea de vigilancia (cada 5 min) y /salud/.
--   · Notificación nueva 'alerta_sistema' (solo administradores) y rumbo.alertar_admins() para crearla
--     sin repetir: la clave la arma la tarea (p. ej. "webhook_silencio:2026-11-23T10") y hay una por hora.

ALTER TABLE rumbo.notificacion DROP CONSTRAINT notificacion_tipo_check;
ALTER TABLE rumbo.notificacion ADD CONSTRAINT notificacion_tipo_check CHECK (tipo IN (
    'lead_nuevo', 'lead_reasignado', 'lead_quitado', 'cliente_escribio', 'plazo_por_vencer', 'hora_de_llamar',
    'llamada_atrasada', 'sin_gestionar_vuelta', 'anuncio_sin_pais', 'alerta_sistema'));

CREATE INDEX webhook_recibido_ix ON rumbo.webhook_evento (recibido_en DESC) WHERE firma_valida;

-- Para quien vigila (sistema) y para el admin (pantalla de métricas / salud). Sin datos personales.
CREATE FUNCTION rumbo.estado_webhook(p_minutos_atascado integer DEFAULT 5)
RETURNS TABLE (ultimo_valido_en timestamptz, recibidos_1h bigint, atascados bigint, agotados_24h bigint,
               con_error_1h bigint, firmas_invalidas_1h bigint, ultimo_error text, en_horario boolean,
               abierto_desde timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
BEGIN
    PERFORM rumbo._exigir_rol('sistema', 'admin');
    RETURN QUERY
    SELECT (SELECT max(w.recibido_en) FROM rumbo.webhook_evento w WHERE w.firma_valida),
           (SELECT count(*) FROM rumbo.webhook_evento w WHERE w.firma_valida AND w.recibido_en > now() - interval '1 hour'),
           -- válidos sin procesar hace más de N minutos y que todavía se reintentan
           (SELECT count(*) FROM rumbo.webhook_evento w
            WHERE w.firma_valida AND w.procesado_en IS NULL AND w.intentos < 10
              AND w.recibido_en < now() - make_interval(mins => p_minutos_atascado)),
           -- agotaron los 10 intentos: ese mensaje no entró al sistema
           (SELECT count(*) FROM rumbo.webhook_evento w
            WHERE w.firma_valida AND w.procesado_en IS NULL AND w.intentos >= 10
              AND w.recibido_en > now() - interval '24 hours'),
           (SELECT count(*) FROM rumbo.webhook_evento w
            WHERE w.ultimo_error IS NOT NULL AND w.procesado_en IS NULL AND w.recibido_en > now() - interval '1 hour'),
           (SELECT count(*) FROM rumbo.webhook_evento w WHERE NOT w.firma_valida AND w.recibido_en > now() - interval '1 hour'),
           (SELECT left(w.ultimo_error, 300) FROM rumbo.webhook_evento w
            WHERE w.ultimo_error IS NOT NULL AND w.procesado_en IS NULL ORDER BY w.id DESC LIMIT 1),
           rumbo.en_horario(),
           rumbo.inicio_turno();
END $$;

CREATE FUNCTION rumbo.alertar_admins(p_clave text, p_titulo text, p_mensaje text, p_url text DEFAULT NULL)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, rumbo AS $$
DECLARE
    u       record;
    v_total integer := 0;
BEGIN
    PERFORM rumbo._exigir_rol('sistema');
    IF length(btrim(coalesce(p_clave, ''))) NOT BETWEEN 3 AND 200 THEN
        RAISE EXCEPTION 'Clave de alerta inválida' USING ERRCODE = 'RB422';
    END IF;
    FOR u IN SELECT id FROM rumbo.usuario WHERE activo AND rol = 'admin' LOOP
        INSERT INTO rumbo.notificacion (usuario_id, tipo, titulo, mensaje, url, clave)
        VALUES (u.id, 'alerta_sistema', left(p_titulo, 200), left(p_mensaje, 1000), p_url, p_clave)
        ON CONFLICT ON CONSTRAINT notificacion_clave_uk DO NOTHING;
        IF FOUND THEN
            v_total := v_total + 1;
        END IF;
    END LOOP;
    RETURN v_total;                       -- 0 = ya se había avisado con esa clave
END $$;

GRANT EXECUTE ON FUNCTION rumbo.estado_webhook(integer), rumbo.alertar_admins(text, text, text, text) TO rumbo_app;
