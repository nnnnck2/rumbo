# Rumbo · Base de datos (PostgreSQL 17)

## Levantar

```bash
cd db
cp .env.example .env        # poner claves reales: openssl rand -base64 32
docker compose up -d --build
```

Al crear el volumen por primera vez se crean los roles, se aplican las migraciones y se toma el primer respaldo completo. El contenedor solo se marca como sano cuando todo eso terminó.

Las pruebas corren en una pila desechable con sus propios volúmenes y no tocan la base de desarrollo:

```bash
bash pruebas/probar.sh
```

## Qué garantiza y dónde está

| Requisito | Cómo se cumple | Archivo |
|---|---|---|
| **Integridad transaccional** | Las reglas de negocio están en CHECK, FK, UNIQUE y triggers: teléfono E.164, máquina de estados de etapas, ventas que no se modifican, historiales de solo inserción, sin DELETE ni TRUNCATE. Cada migración corre en una sola transacción. | `003`, `004` |
| **Concurrencia y bloqueos** | Las funciones toman los bloqueos siempre en el mismo orden (candado de reparto → lead → asesor), así no hay deadlocks. El lead se crea con `INSERT … ON CONFLICT` para que sea idempotente. La versión del registro actúa como bloqueo optimista. Las colas usan `SKIP LOCKED`, y cada rol tiene `lock_timeout`, `statement_timeout` e `idle_in_transaction_session_timeout`. | `006`, `00-roles.sh` |
| **Índices y rendimiento** | Índices parciales para la lista de llamadas y la cola, GIN sobre `jsonb`, trigramas para buscar por nombre, BRIN en la auditoría y `fillfactor 90` para que las actualizaciones sean HOT. `pg_stat_statements` registra las consultas lentas. | `003`, `postgresql.conf` |
| **Seguridad y RLS** | Cada rol tiene el mínimo privilegio. La RLS falla cerrada: sin contexto no se ve nada. Hay permisos por columna, las operaciones pasan por funciones que validan el rol, las conexiones exigen TLS y SCRAM, el superusuario no entra por red y CALLFLOW solo ve vistas sin datos personales. | `007`, `009`, `pg_hba.conf` |
| **Trazabilidad y auditoría** | Hay una auditoría inmutable de quién, cuándo, desde dónde y qué columnas cambiaron, más historiales de etapas, asignaciones e intentos. Los datos personales quedan como hash. | `005`, `004` |
| **Modelado híbrido** | Las columnas relacionales cubren lo que se filtra o se une. `jsonb` validado guarda lo variable (datos de campaña, preferencias, payloads), con columnas generadas e indexadas desde ese `jsonb`. | `003` |
| **Alta disponibilidad y PITR** | Una réplica en streaming (hot standby). El WAL se archiva continuamente cada 60 s como máximo. Los respaldos se cifran con AES-256 usando pgBackRest y se puede restaurar a cualquier segundo con `scripts/restaurar_pitr.sh`. Las páginas llevan checksums. | `postgresql.conf`, `pgbackrest.conf`, `scripts/` |
| **LOPDP** | `anonimizar_lead()` borra los datos personales y conserva las métricas. La auditoría no guarda esos datos en claro. | `006` |

## Roles

| Rol | Uso | Puede |
|---|---|---|
| `rumbo_app` | Django y Celery | Leer con RLS, editar `lead.datos`, `nombre_perfil` y `consentimiento_en`, agregar notas y ejecutar las funciones de negocio |
| `rumbo_callflow` | CALLFLOW (comisiones) | Leer `api.ventas` y `api.asesores`. Solo lectura y sin datos personales |
| `rumbo_migrator` | Migraciones | Entra como `rumbo_owner`, el dueño de los objetos |
| `rumbo_replicacion` | Réplica | Solo replicación |

## Conectar Django

1. **Contexto por transacción.** Con `ATOMIC_REQUESTS = True`, un middleware ejecuta al inicio de cada request:
   ```python
   cursor.execute("SELECT set_config('rumbo.usuario_id', %s, true)", [str(request.user.id)])
   ```
   Los workers de Celery usan el id `0` (sistema). El rol y el asesor **no** los manda la app: la base los lee de `rumbo.usuario`.
2. **Modelos `managed = False`.** Las tablas las crean estas migraciones SQL, no `makemigrations`. Las tablas propias de Django (auth, sesiones) van en un esquema `django` aparte; ese esquema se crea con una migración nueva cuando se arme el proyecto Django (SCRUM-14).
3. **Las escrituras de negocio se hacen con funciones**, no con el ORM:
   `registrar_mensaje_entrante`, `registrar_intento`, `cambiar_etapa`, `reasignar_manual`, `cambiar_estado_asesor`, `registrar_mensaje_saliente`, `anular_venta`.
4. **Errores propios** que la app debe traducir para el usuario:
   - `RB409`: otro usuario cambió el lead; hay que recargar.
   - `RB422`: regla de negocio.
   - `RB403`: operación prohibida.
   - `42501`: sin permiso.
5. **Tareas de Celery beat:**
   - `rumbo.reasignar_sin_primera_llamada()`: cada minuto.
   - `rumbo.liberar_cola()`: a las 9:00 y cada 5 minutos.

## Respaldos en el VPS (crontab del host)

```cron
0 3 * * 0    cd /opt/rumbo/db && docker compose exec -T -u postgres db /scripts/respaldo.sh full
0 3 * * 1-6  cd /opt/rumbo/db && docker compose exec -T -u postgres db /scripts/respaldo.sh diff
30 4 * * *   cd /opt/rumbo/db && docker compose exec -T -u postgres db /scripts/verificar_respaldos.sh
```

Restaurar a un momento exacto: `./scripts/restaurar_pitr.sh "2027-01-15 10:42:00-05"`

## Antes de producción

- **Copia fuera del VPS.** Hay que activar `repo2` (S3/B2/R2) en `pgbackrest.conf`. Un respaldo que vive en el mismo servidor no sirve si se pierde el servidor.
- **Réplica en otro servidor.** Con la réplica en el mismo VPS se protegen los datos, pero no se tiene alta disponibilidad real si el VPS se cae. Para eso hay que mover `db-replica` a un segundo VPS.
- **Certificado TLS real.** Hay que montarlo en `/etc/postgresql/ssl`; el de la imagen es autofirmado.
- **Guardar fuera del servidor la clave `PGBACKREST_REPO1_CIPHER_PASS`.** Sin ella los respaldos no se pueden leer.
- **Confirmar con el área los valores pendientes** de `010_datos_iniciales.sql`: días de atención y minutos máximos.
