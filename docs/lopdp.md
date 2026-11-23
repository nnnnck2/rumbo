# Rumbo · Protección de datos personales (LOPDP Ecuador, 2021) — SCRUM-43

Cómo cumple Rumbo la Ley Orgánica de Protección de Datos Personales. Lo marcado **(validar con el área)** es una
propuesta técnica: lo debe confirmar Multivisa (responsable del tratamiento) con su asesoría legal.

## 1. Finalidad del tratamiento

| | |
|---|---|
| **Responsable** | Multivisa (razón social y RUC: **validar con el área**). |
| **Finalidad** | Atender la consulta del cliente sobre trámites de visa: contactarlo por teléfono o WhatsApp, asesorarlo, agendar citas, pedir documentos y dar seguimiento al trámite. Medir la atención (tiempos, contactos, ventas) para mejorarla y calcular comisiones de los asesores. |
| **No se usa para** | Publicidad de terceros, venta o cesión de datos, ni decisiones automatizadas que afecten al cliente. El reparto automático solo decide **qué asesor** lo llama. |
| **Base de legitimación** | Consentimiento del titular (art. 7 y 8) y ejecución de medidas precontractuales a pedido del titular: el cliente es quien escribe o llama pidiendo información. |
| **Datos que se tratan** | Teléfono, nombre de perfil de WhatsApp, mensajes que el cliente envía, tipo de visa y país de interés, fecha de la cita, documentos pedidos/recibidos (solo el estado, no los archivos), notas del asesor, resultado de cada llamada y venta. **No** se piden datos sensibles. |
| **Origen** | El propio titular (WhatsApp, llamada, visita) o un referido; en anuncios de Meta, el anuncio del que llegó. |

## 2. Información al titular (aviso de privacidad)

- **WhatsApp**: la respuesta automática al primer mensaje termina con el aviso configurable `texto_privacidad`
  (Configuración → WhatsApp). Valor actual:
  > Al escribirnos, Multivisa tratará tus datos solo para atender tu consulta, conforme a la Ley Orgánica de
  > Protección de Datos Personales. Puedes pedir acceso, rectificación o eliminación de tus datos respondiendo a este chat.
- La ficha del cliente muestra **cuándo** se le envió el aviso (`rumbo.aviso_privacidad_enviado`, migración 025).
- **Llamada o visita**: la pantalla "Registrar cliente" recuerda al asesor qué decirle antes de registrarlo.

## 3. Consentimiento registrado

- La ficha tiene el bloque **Datos personales**: el asesor dueño del cliente (o un supervisor) registra que el
  cliente aceptó y **por qué medio** (teléfono, WhatsApp, oficina o formulario firmado).
- Al registrar un cliente a mano se puede marcar en el mismo formulario.
- Se guarda la fecha en `lead.consentimiento_en` y la evidencia (medio, quién lo registró y cuándo) en
  `lead.datos.consentimiento`. La primera constancia no se puede pisar y el cambio queda en la auditoría inmutable.
- Función: `rumbo.registrar_consentimiento()` (025). Pruebas: `db/pruebas/17_consentimiento_lopdp.sql`.

## 4. Derechos del titular (acceso, rectificación, eliminación, oposición)

- Pantalla **Datos personales** (solo administrador, SCRUM-120): se registra cada solicitud con un plazo de
  **15 días** y se cierra con la respuesta dada al cliente.
- **Eliminación**: `rumbo.anonimizar_lead()` borra teléfono, nombre, datos y el texto de los mensajes y conserva solo
  las cifras (para métricas y comisiones). La auditoría nunca guardó esos datos en claro (solo un hash), así que no hay
  que reescribirla.
- **Rectificación**: el asesor corrige tipo de visa, país y cita en la ficha; el admin puede editar el resto.

## 5. Conservación

**(validar con el área)** Propuesta: clientes sin venta, 2 años desde el último contacto; clientes con venta, lo que
exija la normativa tributaria y contable (7 años). Al vencer el plazo se anonimizan. Los respaldos cifrados se
conservan 2 meses (ver `db/README.md`) y se renuevan solos.

## 6. Seguridad y control de acceso por rol (verificado)

| Medida | Dónde | Verificación |
|---|---|---|
| Cada asesor ve **solo sus clientes**; supervisor ve el equipo; admin todo. Falla cerrada: sin usuario no se ve nada. | RLS en la base (`007_rls.sql`), no en la app | `db/pruebas/02_seguridad_rls.sql`: "asesor ve solo su lead", "asesor no puede editar leads ajenos", "supervisor no ve la auditoría", "sin contexto: 0 usuarios visibles"… |
| Las pantallas se ocultan según el rol | `cuentas/permisos.py` | `cuentas/tests/test_cuentas.py` (matriz de roles) |
| Contraseñas robustas, bloqueo tras 5 fallos, registro de ingresos | SCRUM-35 (migración 020) | `db/pruebas/12_seguridad_acceso.sql`, `cuentas/tests/test_acceso.py` |
| Auditoría inmutable de cambios (sin datos personales en claro) | `005_auditoria.sql` | `02_seguridad_rls.sql`: "nadie escribe la auditoría a mano" |
| Conexiones cifradas: HTTPS (HSTS) y TLS obligatorio a la base | `infra/`, `pg_hba.conf` | `probar.sh`: "conexión sin TLS rechazada" |
| Respaldos cifrados (AES-256) dentro y fuera del servidor | pgBackRest | `probar.sh`: PITR |
| CALLFLOW solo recibe ventas y asesores, sin datos de clientes | API de SCRUM-57 | `db/pruebas/16_api_callflow.sql`: "sin datos personales del cliente" |
| Los errores enviados a Sentry no llevan datos personales | `send_default_pii=False` (SCRUM-41) | `config/settings/base.py` |

## 7. Encargados y transferencias

| Encargado | Qué recibe | Nota |
|---|---|---|
| Meta (WhatsApp Cloud API) | Mensajes con el cliente | Servidores fuera de Ecuador: transferencia internacional. **(validar con el área)** mencionarlo en el aviso de privacidad completo publicado en la web. |
| Proveedor del VPS (SCRUM-12) | Toda la base, cifrada en tránsito | Elegir uno con contrato de encargo de tratamiento. |
| Almacenamiento S3 de respaldos | Respaldos cifrados (la clave queda en el servidor) | El proveedor no puede leerlos. |
| Sentry (opcional) | Errores técnicos sin datos personales | Solo si se configura `SENTRY_DSN`. |

## 8. Pendientes del área

- Razón social, RUC y contacto del responsable (o delegado de protección de datos) para el aviso completo.
- Aprobar el plazo de conservación del punto 5.
- Publicar la política de privacidad completa en la web y enlazarla desde el aviso de WhatsApp.
