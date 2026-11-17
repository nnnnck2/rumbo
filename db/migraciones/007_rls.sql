-- 007 · Row Level Security
-- Reglas:
--   · asesor      → solo sus leads y lo que cuelga de ellos (mensajes, intentos, notas, ventas)
--   · supervisor  → todo lo operativo; no modifica usuarios ni configuración
--   · admin       → todo
--   · sistema     → workers (webhook, reparto, tareas programadas)
--   · sin contexto → nada (falla cerrada)
-- (SELECT rumbo.ctx_...()) entre paréntesis hace que PostgreSQL lo evalúe una sola vez por
-- consulta y no una vez por fila.
-- RLS se aplica a rumbo_app. El dueño (rumbo_owner) no la tiene forzada porque las funciones
-- SECURITY DEFINER de 006 necesitan ver todo para repartir; esas funciones validan el rol.

ALTER TABLE rumbo.usuario              ENABLE ROW LEVEL SECURITY;
ALTER TABLE rumbo.numero_whatsapp      ENABLE ROW LEVEL SECURITY;
ALTER TABLE rumbo.asesor               ENABLE ROW LEVEL SECURITY;
ALTER TABLE rumbo.lead                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE rumbo.nota_lead            ENABLE ROW LEVEL SECURITY;
ALTER TABLE rumbo.lead_etapa_historial ENABLE ROW LEVEL SECURITY;
ALTER TABLE rumbo.asignacion           ENABLE ROW LEVEL SECURITY;
ALTER TABLE rumbo.intento_llamada      ENABLE ROW LEVEL SECURITY;
ALTER TABLE rumbo.mensaje_whatsapp     ENABLE ROW LEVEL SECURITY;
ALTER TABLE rumbo.webhook_evento       ENABLE ROW LEVEL SECURITY;
ALTER TABLE rumbo.venta                ENABLE ROW LEVEL SECURITY;
ALTER TABLE rumbo.configuracion        ENABLE ROW LEVEL SECURITY;
ALTER TABLE rumbo.etapa                ENABLE ROW LEVEL SECURITY;
ALTER TABLE rumbo.etapa_transicion     ENABLE ROW LEVEL SECURITY;
ALTER TABLE rumbo.resultado_llamada    ENABLE ROW LEVEL SECURITY;
ALTER TABLE rumbo.motivo_descarte      ENABLE ROW LEVEL SECURITY;
ALTER TABLE auditoria.registro         ENABLE ROW LEVEL SECURITY;

-- ── Usuarios ────────────────────────────────────────────────────────────────────
CREATE POLICY usuario_leer ON rumbo.usuario FOR SELECT TO rumbo_app
    USING (id = (SELECT rumbo.ctx_usuario_id())
           OR (SELECT rumbo.ctx_rol()) IN ('supervisor', 'admin', 'sistema'));
CREATE POLICY usuario_admin ON rumbo.usuario FOR ALL TO rumbo_app
    USING ((SELECT rumbo.ctx_rol()) = 'admin')
    WITH CHECK ((SELECT rumbo.ctx_rol()) = 'admin' AND rol <> 'sistema');

-- ── Asesores ────────────────────────────────────────────────────────────────────
CREATE POLICY asesor_leer ON rumbo.asesor FOR SELECT TO rumbo_app
    USING (id = (SELECT rumbo.ctx_asesor_id())
           OR (SELECT rumbo.ctx_rol()) IN ('supervisor', 'admin', 'sistema'));
CREATE POLICY asesor_admin ON rumbo.asesor FOR ALL TO rumbo_app
    USING ((SELECT rumbo.ctx_rol()) = 'admin')
    WITH CHECK ((SELECT rumbo.ctx_rol()) = 'admin');

-- ── Leads ───────────────────────────────────────────────────────────────────────
CREATE POLICY lead_leer ON rumbo.lead FOR SELECT TO rumbo_app
    USING ((SELECT rumbo.ctx_rol()) IN ('supervisor', 'admin', 'sistema')
           OR asesor_id = (SELECT rumbo.ctx_asesor_id()));
-- La app solo puede editar columnas "libres" (ver 009); USING y WITH CHECK impiden tocar
-- leads ajenos o pasarse un lead a otro asesor.
CREATE POLICY lead_editar ON rumbo.lead FOR UPDATE TO rumbo_app
    USING      ((SELECT rumbo.ctx_rol()) IN ('supervisor', 'admin') OR asesor_id = (SELECT rumbo.ctx_asesor_id()))
    WITH CHECK ((SELECT rumbo.ctx_rol()) IN ('supervisor', 'admin') OR asesor_id = (SELECT rumbo.ctx_asesor_id()));

-- ── Todo lo que cuelga de un lead: visible si el lead es visible ────────────────
-- La subconsulta sobre rumbo.lead aplica a su vez la política lead_leer.
CREATE POLICY nota_leer ON rumbo.nota_lead FOR SELECT TO rumbo_app
    USING (EXISTS (SELECT 1 FROM rumbo.lead l WHERE l.id = lead_id));
CREATE POLICY nota_crear ON rumbo.nota_lead FOR INSERT TO rumbo_app
    WITH CHECK (autor_usuario_id = (SELECT rumbo.ctx_usuario_id())
                AND (SELECT rumbo.ctx_rol()) IN ('asesor', 'supervisor', 'admin')
                AND EXISTS (SELECT 1 FROM rumbo.lead l WHERE l.id = lead_id));

CREATE POLICY etapa_hist_leer ON rumbo.lead_etapa_historial FOR SELECT TO rumbo_app
    USING (EXISTS (SELECT 1 FROM rumbo.lead l WHERE l.id = lead_id));
CREATE POLICY asignacion_leer ON rumbo.asignacion FOR SELECT TO rumbo_app
    USING (EXISTS (SELECT 1 FROM rumbo.lead l WHERE l.id = lead_id));
CREATE POLICY intento_leer ON rumbo.intento_llamada FOR SELECT TO rumbo_app
    USING (EXISTS (SELECT 1 FROM rumbo.lead l WHERE l.id = lead_id));
CREATE POLICY mensaje_leer ON rumbo.mensaje_whatsapp FOR SELECT TO rumbo_app
    USING (EXISTS (SELECT 1 FROM rumbo.lead l WHERE l.id = lead_id));
CREATE POLICY mensaje_estado ON rumbo.mensaje_whatsapp FOR UPDATE TO rumbo_app
    USING ((SELECT rumbo.ctx_rol()) = 'sistema')
    WITH CHECK ((SELECT rumbo.ctx_rol()) = 'sistema');
CREATE POLICY venta_leer ON rumbo.venta FOR SELECT TO rumbo_app
    USING (EXISTS (SELECT 1 FROM rumbo.lead l WHERE l.id = lead_id));

-- ── Webhook: solo el sistema ────────────────────────────────────────────────────
CREATE POLICY webhook_sistema ON rumbo.webhook_evento FOR SELECT TO rumbo_app
    USING ((SELECT rumbo.ctx_rol()) IN ('sistema', 'admin'));

-- ── Catálogos, números y configuración: lectura para cualquier usuario activo, ──
--    escritura solo admin.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['numero_whatsapp', 'configuracion', 'etapa', 'etapa_transicion',
                             'resultado_llamada', 'motivo_descarte']
    LOOP
        EXECUTE format($f$CREATE POLICY %I ON rumbo.%I FOR SELECT TO rumbo_app
                          USING ((SELECT rumbo.ctx_rol()) IS NOT NULL)$f$, t || '_leer', t);
        EXECUTE format($f$CREATE POLICY %I ON rumbo.%I FOR ALL TO rumbo_app
                          USING ((SELECT rumbo.ctx_rol()) = 'admin')
                          WITH CHECK ((SELECT rumbo.ctx_rol()) = 'admin')$f$, t || '_admin', t);
    END LOOP;
END $$;

-- ── Auditoría: solo admin la lee; nadie la escribe directamente ─────────────────
CREATE POLICY registro_admin ON auditoria.registro FOR SELECT TO rumbo_app
    USING ((SELECT rumbo.ctx_rol()) = 'admin');
