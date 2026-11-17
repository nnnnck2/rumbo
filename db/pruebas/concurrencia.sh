#!/bin/bash
# Prueba de concurrencia real: muchas conexiones simultáneas.
#   1) 40 leads distintos llegan a la vez, y cada mensaje llega DOS veces en paralelo
#      (Meta reintenta webhooks) → 40 leads, 40 mensajes, 10 por asesor exactos.
#   2) Dos pestañas registran la misma llamada con la misma versión → solo una gana.
# Corre DENTRO del contenedor (probar.sh lo invoca con docker compose exec).
set -euo pipefail
export PGDATABASE=rumbo

psql -v ON_ERROR_STOP=1 -q <<'SQL'
SET ROLE rumbo_owner;
INSERT INTO rumbo.usuario (id, nombre, rol) VALUES (21,'C1','asesor'),(22,'C2','asesor'),(23,'C3','asesor'),(24,'C4','asesor');
INSERT INTO rumbo.asesor (usuario_id, numero_whatsapp_id, estado)
SELECT id, 1, 'disponible' FROM rumbo.usuario WHERE id BETWEEN 21 AND 24;
UPDATE rumbo.configuracion SET valor = '{"inicio":"00:00","fin":"23:59:59","dias":[1,2,3,4,5,6,7],"zona":"UTC"}' WHERE clave = 'horario';
SQL

mensaje() {
    psql -v ON_ERROR_STOP=1 -qtA -c "SET ROLE rumbo_app" -c "SELECT set_config('rumbo.usuario_id','0',false)" \
         -c "SELECT r_lead_id FROM rumbo.registrar_mensaje_entrante('wamid.c$1', '+5939980000$(printf '%02d' "$1")', 'Cliente $1', 1::smallint, 'text', 'hola', '{}', now())" >/dev/null
}

echo "→ 80 webhooks simultáneos (40 mensajes × 2 entregas)"
for i in $(seq 1 40); do
    mensaje "$i" &
    mensaje "$i" &
done
wait

psql -v ON_ERROR_STOP=1 -qtA <<'SQL'
SET ROLE rumbo_owner;
DO $$
DECLARE v_leads int; v_msgs int; v_asig int; v_dist int[];
BEGIN
    SELECT count(*) INTO v_leads FROM rumbo.lead WHERE telefono LIKE '+5939980000%';
    SELECT count(*) INTO v_msgs  FROM rumbo.mensaje_whatsapp WHERE wa_message_id LIKE 'wamid.c%';
    SELECT count(*) INTO v_asig  FROM rumbo.asignacion s JOIN rumbo.lead l ON l.id = s.lead_id WHERE l.telefono LIKE '+5939980000%';
    SELECT array_agg(n ORDER BY n) INTO v_dist FROM (
        SELECT count(*) n FROM rumbo.lead WHERE telefono LIKE '+5939980000%' GROUP BY asesor_id) x;
    IF v_leads <> 40 OR v_msgs <> 40 OR v_asig <> 40 OR v_dist <> '{10,10,10,10}' THEN
        RAISE EXCEPTION 'FALLÓ concurrencia: leads=% mensajes=% asignaciones=% reparto=%', v_leads, v_msgs, v_asig, v_dist;
    END IF;
    RAISE NOTICE 'ok · 80 webhooks simultáneos: 40 leads, 40 mensajes, sin duplicados, reparto %', v_dist;
END $$;
SQL

echo "→ dos usuarios registran la misma llamada con la misma versión"
LEAD="$(psql -qtA -c "SET ROLE rumbo_owner" -c "SELECT id FROM rumbo.lead WHERE telefono = '+593998000001'" | tail -1)"
VERSION="$(psql -qtA -c "SET ROLE rumbo_owner" -c "SELECT version FROM rumbo.lead WHERE id = $LEAD" | tail -1)"
USUARIO="$(psql -qtA -c "SET ROLE rumbo_owner" -c "SELECT a.usuario_id FROM rumbo.lead l JOIN rumbo.asesor a ON a.id = l.asesor_id WHERE l.id = $LEAD" | tail -1)"

intento() {
    psql -qtA -c "SET ROLE rumbo_app" -c "SELECT set_config('rumbo.usuario_id','$USUARIO',false)" \
         -c "SELECT rumbo.registrar_intento($LEAD, $VERSION, 'no_contesta', 'pestaña $1')" >/tmp/intento_$1.log 2>&1 \
        && echo ok || echo conflicto
}
intento 1 >/dev/null &
intento 2 >/dev/null &
wait
exitos=$(grep -L "RB409\|modificado por otro usuario" /tmp/intento_1.log /tmp/intento_2.log | wc -l)
conflictos=$(grep -l "modificado por otro usuario" /tmp/intento_1.log /tmp/intento_2.log | wc -l)
intentos=$(psql -qtA -c "SET ROLE rumbo_owner" -c "SELECT count(*) FROM rumbo.intento_llamada WHERE lead_id = $LEAD" | tail -1)
if [ "$exitos" -ne 1 ] || [ "$conflictos" -ne 1 ] || [ "$intentos" -ne 1 ]; then
    echo "FALLÓ bloqueo optimista: éxitos=$exitos conflictos=$conflictos intentos guardados=$intentos" >&2
    cat /tmp/intento_1.log /tmp/intento_2.log >&2
    exit 1
fi
echo "ok · bloqueo optimista: 1 gana, 1 recibe conflicto (RB409), 1 intento guardado"
