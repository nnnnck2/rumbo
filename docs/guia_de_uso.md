# Rumbo · Guía de uso

Guía corta para asesores y supervisores del área de visas de Multivisa (SCRUM-46).

Rumbo recibe a los clientes que escriben por WhatsApp desde los anuncios y los reparte entre los asesores que están en turno. **El asesor llama al cliente por teléfono** y registra en Rumbo cómo le fue con cada llamada.

---

## Para todos

**Ingresar:** abra Rumbo en el navegador del computador o del celular e ingrese con el usuario y la contraseña que le dio el administrador. Si la olvidó, pídale al administrador una nueva.

**Horario de atención:** de 9:00 a 18:00 (el administrador lo puede cambiar). Los clientes que escriben fuera de horario esperan en una cola y se reparten al abrir.

---

## Asesor

### 1. Marque su estado

En la barra de arriba elija su estado con un clic:

| Estado | Qué significa |
|---|---|
| **Disponible** | Está listo para llamar: recibe leads nuevos. |
| **En pausa** | Almuerzo, reunión, baño: no recibe leads nuevos. |
| **Fuera de turno** | Terminó su jornada: no recibe leads nuevos. |

Sus leads ya asignados siguen siendo suyos aunque esté en pausa.

### 2. Llame a sus leads

1. Entre a **Leads** y marque **"Por llamar ahora"**. Ahí aparecen los clientes que le toca llamar, del más atrasado al más reciente. Las llamadas vencidas salen en rojo.
2. Abra la ficha del cliente y toque **Llamar**: se abre el marcador del celular con el número.
3. Antes de llamar, revise los mensajes que el cliente escribió por WhatsApp y las notas de otros asesores.

> ⏱️ Tiene **30 minutos** (de turno) para gestionar un lead nuevo, es decir, registrar al menos una llamada. Si no, el lead pasa automáticamente al siguiente asesor en turno; cuando ya pasó por todos, vuelve al primero, así ningún cliente se queda sin atender. La etiqueta de color de cada cliente dice cuánto le queda: verde (a tiempo), amarillo (menos de 15 min), rojo (menos de 5 min).

### 3. Registre SIEMPRE el resultado de cada llamada

**Esto es lo más importante.** Si no registra el resultado, el sistema cree que no llamó: el lead se le quita, el supervisor recibe una alerta y su trabajo no se cuenta en las métricas ni en las comisiones.

Al colgar, en **Resultado de la llamada** toque la opción que corresponde y luego **Registrar**:

| Resultado | Cuándo usarlo | Qué hace Rumbo |
|---|---|---|
| **No contesta / buzón** | No respondió o salió el buzón. | Le envía al cliente un WhatsApp ("le llamamos y no pudimos comunicarnos") y programa el reintento en 30 minutos. Al **3.er** intento sin contacto, el lead pasa a otro asesor. Si entre todos los asesores se llega al tope (9 por defecto), el lead se descarta solo. |
| **Llamar después** | Habló con el cliente y le pidió que lo llame otro día u otra hora. | Pide la fecha y hora, y el lead le vuelve a aparecer en ese momento. |
| **Contactado · interesado** | Habló con el cliente y quiere avanzar. | Pasa el lead a "En asesoría". |
| **Contactado · no interesado** | Habló con el cliente y no quiere seguir. | Descarta el lead con ese motivo. |
| **Número inválido** | El número no existe o no es del cliente. | Descarta el lead. |
| **Venta cerrada** | El cliente contrató. | Pide **tipo de visa y valor**, registra la venta para las comisiones (CALLFLOW) y cierra el lead. |

Puede agregar una nota corta en cada resultado, por ejemplo "prefiere que lo llamen en la tarde".

### Antes de llamar

- **Hora del cliente:** la ficha muestra qué hora es donde está el cliente (por el prefijo de su teléfono). Si allá es muy temprano o muy tarde, aparece un aviso junto a **Llamar**.
- **Guion de llamada:** las preguntas y documentos clave según el tipo de visa del cliente. Se abre solo en la primera llamada.
- **WhatsApp:** el botón verde junto a **Llamar** abre el chat del cliente con un saludo ya escrito.

### 4. Mantenga la ficha al día

- **Datos del caso:** tipo de visa y país de interés. Elija una sugerencia o escriba otro valor.
- **Etapa:** muévala a medida que avanza el trámite (en contacto → en asesoría → documentos → pago → cita agendada). Para **descartar** un lead hay que elegir el motivo.
- **Agendar llamada:** sirve para dejar programada la próxima llamada sin haber llamado todavía, por ejemplo si el cliente pidió por WhatsApp que lo llamen mañana.
- **Notas internas:** solo las ve el equipo, nunca el cliente. No se pueden borrar: escriba con cuidado.

### Notificaciones

La campana de arriba avisa con un sonido y un mensaje en la esquina de la pantalla: cliente nuevo o reasignado, cliente que volvió a escribir, quedan 10 minutos para gestionar, hora de una llamada programada y cliente que pasó a otro asesor. En la campana, **"Avisarme aunque esté en otra pestaña"** activa los avisos del navegador.

### 5. Si el cliente vuelve a escribir

Le llega a usted, que ya conoce su caso, aunque esté en pausa. Si usted ya no está en la empresa, pasa a otro asesor.

- Si el cliente estaba **descartado**, el lead se reabre como **Nuevo** y entra al reparto.
- Si el cliente ya **compró**, el lead no cambia, pero a usted le llega el aviso "cliente con venta le escribió".

### Su meta del día

En **Inicio** ve cuántas llamadas, citas y ventas lleva hoy frente a la meta que fijó la empresa. La barra se pone verde cuando la cumple.

---

## Supervisor

### En vivo

**En vivo** muestra al equipo en este momento: el estado de cada asesor y desde cuándo está así, sus clientes abiertos, los que ya toca llamar, los que aún no gestionó, sus llamadas de hoy y cuándo hizo la última. Arriba están los clientes en cola, los que no han recibido la primera llamada y las llamadas atrasadas. Se actualiza sola cada 15 segundos.

### Asesores

En **Asesores** ve el estado de todo el equipo y cuántos leads abiertos tiene cada uno, y puede cambiarle el estado a cualquier asesor (por ejemplo, poner en pausa a alguien que se fue sin marcar).

### Tablero

En **Tablero** ve una columna por asesor con sus clientes abiertos, cada uno con su color: verde a tiempo, amarillo por vencer, rojo urgente, azul con llamada programada. Se actualiza sola cada 30 segundos. En la ficha de cada cliente, **Recorrido** muestra por qué asesores pasó en esta vuelta y quiénes faltan.

### Alertas

El enlace **Alertas** de la barra muestra en rojo cuántos leads llevan más de **30 minutos** de atraso: sin primera llamada, con el reintento o la llamada agendada vencidos, o en cola sin nadie en turno. La página se actualiza sola cada 30 segundos.

- Toque **Activar notificaciones del navegador** para que le avise aunque esté en otra pestaña.
- Desde cada alerta puede abrir la ficha y reasignar el lead.

### Reasignar

- **Un lead:** en la ficha, bloque **Reasignar**, elija el asesor.
- **Varios leads:** en **Leads**, márquelos, elija el asesor y toque **Reasignar seleccionados**. Si alguno no se puede (por ejemplo, porque está cerrado), Rumbo lo indica y reasigna el resto.

Queda registrado quién reasignó, a quién y cuándo.

### Métricas

En **Métricas**, elija el período y vea:

- leads recibidos;
- tiempo desde que se asigna un lead hasta la primera llamada;
- tasa de contacto;
- ventas;
- posibles errores, como leads sin respuesta automática;
- el **embudo por campaña y anuncio** (leads, contactados, citas y ventas), con el costo por lead y por venta si el administrador registró la inversión;
- el detalle por asesor.

**Exportar a Excel:** en **Métricas** y en **Leads** (respeta la pestaña, la búsqueda y los filtros). Cada exportación queda registrada.

En **Leads → Más filtros**, **"Llegaron por varios anuncios"** muestra a los clientes que escribieron desde más de un anuncio. Esos clientes cuentan solo para el primer anuncio.

---

## Administrador

- **Usuarios:** crear cuentas (asesor, supervisor o administrador), asignar a cada asesor su número de WhatsApp y su código de CALLFLOW, cambiar contraseñas y desactivar a quien deja la empresa. Un usuario desactivado no puede ingresar, y sus leads pasan a otros asesores cuando el cliente vuelve a escribir o cuando se reasignan.
- **Campañas:** cada anuncio de Facebook / Instagram del que llegan clientes aparece solo. Asígnele su **país**: los clientes de ese anuncio (los que llegaron y los que lleguen) quedan con ese país de interés. En **Métricas** se ven leads, contacto y ventas por campaña. Escriba la **inversión total** de cada anuncio para ver el costo por lead y por venta.
- **Configuración:** horario de atención, intentos por asesor, tope de intentos por cliente, minutos para la primera llamada, minutos entre reintentos, minutos para alertar al supervisor, textos automáticos de WhatsApp (bienvenida, fuera de horario con `{proxima_apertura}` y aviso de privacidad), el WhatsApp de "no contesta" (texto y plantilla de Meta), la meta del día de los asesores y el guion de llamada por tipo de visa. Los cambios rigen de inmediato.
- **Conversiones para Meta:** cuando un cliente que llegó por un anuncio agenda una cita o compra, Rumbo se lo informa a Meta para que optimice los anuncios. Para activarlo hay que poner `META_DATASET_ID`, `META_CAPI_TOKEN` y `META_WABA_ID` en el `.env` del servidor. A Meta solo se envía el teléfono cifrado (hash), el id del clic y el valor de la venta.

---

## Más herramientas

**Para el asesor**
- **Responder por WhatsApp desde la ficha:** escriba en la caja de la conversación o toque una respuesta rápida. Sale por el número de la empresa y queda en la ficha. Solo se puede escribir texto si el cliente escribió en las últimas 24 h.
- **Documentos:** en la ficha, toque cada documento para pasarlo de *falta* a *pedido* y a *recibido*. "Pedir lo que falta" prepara el mensaje de WhatsApp.
- **Fecha de la cita:** en Datos del caso. El cliente recibe un recordatorio 24 h y 2 h antes, y la cita aparece en la **Agenda**.
- **Prioridad alta:** "Llamar al siguiente" empieza por los clientes más calientes (llegaron por un anuncio, respondieron las preguntas, volvieron a escribir, tienen cita).
- **Deshacer:** al tocar un resultado hay 5 segundos para tocar **Deshacer** antes de que se guarde.
- **Buscar un cliente:** lupa de arriba o **Ctrl + K** (o la tecla **/**).
- **Comisión del mes:** en Inicio, una estimación según la regla de la empresa. La oficial la calcula CALLFLOW.
- **Avisos en el celular:** menú de usuario → **Activar avisos en este dispositivo**. En el celular, "Agregar a la pantalla de inicio" instala Rumbo como una app.
- **Tema oscuro:** menú de usuario → Tema.

**Para la supervisora**
- **Métricas:** mapa de las mejores horas para contactar y "Para acompañar esta semana" (asesores muy por debajo del equipo).
- **Agenda** de todo el equipo, con filtro por asesor.

**Para el administrador**
- **Datos personales (LOPDP):** registrar pedidos de clientes, ver el plazo de 15 días, responder y, si piden eliminación, anonimizar.
- **Usuarios → asesor:** países y tipos de visa que domina (el reparto los prefiere).
- **Configuración:** preguntas automáticas, recordatorio de citas, respuestas rápidas, documentos por visa, comisión estimada y destinatarios del reporte semanal de los lunes.

---

## Sesión práctica (60 minutos)

| Tiempo | Actividad |
|---|---|
| 10 min | Qué es Rumbo y por qué registrar cada llamada (reparto, alertas, comisiones). |
| 10 min | Ingreso, estados y lista "Por llamar ahora", en el celular de cada asesor. |
| 25 min | **Práctica:** el supervisor simula leads de prueba y cada asesor recorre los 6 resultados de llamada, agenda una llamada, completa los datos del caso y deja una nota. |
| 10 min | Supervisores: alertas, reasignación y métricas. |
| 5 min | Preguntas y dudas. |

**Antes de la sesión:**
- Crear las cuentas de todos.
- Tener leads de prueba: `python manage.py simular_mensaje_whatsapp --telefono +5939… --texto "Hola"`.
- Probar el ingreso desde el celular de un asesor.
