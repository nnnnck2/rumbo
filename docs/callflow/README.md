# Integración Rumbo → CALLFLOW (SCRUM-57, RF-35)

CALLFLOW calcula las comisiones de las ventas de visas igual que las suyas, sin digitarlas: **consulta** a Rumbo
por HTTPS. CALLFLOW nunca recibe conexiones (sigue en la red local de la oficina).

```
CALLFLOW (oficina) ──HTTPS GET + token──► nginx ──► Rumbo /api/callflow/v1/… ──► rumbo.venta (solo lectura)
```

## Endpoints

| Método | Ruta | Devuelve |
|---|---|---|
| GET | `/api/callflow/v1/ventas/?desde=&despues_id=&limite=` | Ventas nuevas o cambiadas desde el punto dado, en orden (`actualizado_en`, `venta_id`). Máximo 1000 por página. |
| GET | `/api/callflow/v1/asesores/` | Asesores con su `codigo_callflow` (código de empleado) y si están activos. |

Encabezado obligatorio: `Authorization: Bearer <token>`. Sin token o con uno inválido: **401**. Cualquier otro método: 405.

Cada venta trae `venta_id`, `asesor_id`, `asesor_codigo_callflow`, `tipo_visa`, `pais`, `valor` (texto con dos
decimales, para leerlo como `Decimal`), `moneda`, `cerrada_en`, `anulada_en` y `actualizado_en`. **No** trae
ningún dato del cliente (teléfono, nombre, mensajes ni notas): LOPDP.

### Sincronización incremental

1. La primera vez, sin parámetros.
2. Guardar `siguiente` de la respuesta y pedir con esos valores mientras `hay_mas` sea `true`.
3. En la próxima sincronización (p. ej. cada hora), empezar desde el último `siguiente` guardado.
4. Si una venta llega con `anulada_en`, se anuló en Rumbo: CALLFLOW revierte esa comisión.

`docs/callflow/cliente_rumbo.py` hace todo eso con la biblioteca estándar de Python, más un cálculo de comisiones de ejemplo:

```bash
RUMBO_API_URL=https://<dominio> RUMBO_API_TOKEN=rbcf_… python cliente_rumbo.py 2026-11
# 3 asesores · 3 ventas · próxima sincronización desde {...}
#   EMP-BETO: 2 venta(s) · total 649.99 · comisión 32.50
```

## Token

```bash
docker compose exec web python manage.py generar_token_callflow
```

- El **token** va al `.env` de CALLFLOW (`RUMBO_API_TOKEN`). No se guarda en Rumbo.
- Su **SHA-256** va al `.env` de Rumbo: `CALLFLOW_API_TOKENS_SHA256=<hash>` y `docker compose up -d web`.
- Para rotarlo sin cortar: agregar el hash nuevo separado por coma, cambiar CALLFLOW y después quitar el viejo.
- Sin `CALLFLOW_API_TOKENS_SHA256` la API queda cerrada (todo 401).

## Seguridad

- Solo GET, token en tiempo constante (`hmac.compare_digest`), límite de 2 peticiones/s por IP en nginx.
- Cada consulta (y cada token inválido) queda en el log `rumbo.seguridad` con la IP.
- En la base, la API lee con `api.callflow_ventas()` y `api.callflow_asesores()` (migración 024), que solo
  devuelven las vistas `api.ventas` y `api.asesores` de la migración 008.
- El acceso directo a PostgreSQL con el rol `rumbo_callflow` (008) sigue disponible para una red privada,
  pero en producción se recomienda la API: no hay que abrir el puerto de la base.

## Pendiente del lado de CALLFLOW

Agregar en CALLFLOW la tarea que use este cliente y cargue las ventas en su cálculo de comisiones (proyecto
CALLFLOW, rama de Gabo). Probado contra Rumbo local: sincronización completa, incremental, venta anulada y
cálculo por código de empleado.
