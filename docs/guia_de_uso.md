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

> ⏱️ Tiene **15 minutos** para la primera llamada de un lead nuevo. Si no registra ningún intento en ese tiempo, el lead pasa a otro asesor.

### 3. Registre SIEMPRE el resultado de cada llamada

**Esto es lo más importante.** Si no registra el resultado, el sistema cree que no llamó: el lead se le quita, el supervisor recibe una alerta y su trabajo no se cuenta en las métricas ni en las comisiones.

Al colgar, en **Resultado de la llamada** toque la opción que corresponde y luego **Registrar**:

| Resultado | Cuándo usarlo | Qué hace Rumbo |
|---|---|---|
| **No contesta / buzón** | No respondió o salió el buzón. | Programa el reintento en 30 minutos. Al **3.er** intento sin contacto, el lead pasa a otro asesor. |
| **Llamar después** | Habló con el cliente y le pidió que lo llame otro día u otra hora. | Pide la fecha y hora, y el lead le vuelve a aparecer en ese momento. |
| **Contactado · interesado** | Habló con el cliente y quiere avanzar. | Pasa el lead a "En asesoría". |
| **Contactado · no interesado** | Habló con el cliente y no quiere seguir. | Descarta el lead con ese motivo. |
| **Número inválido** | El número no existe o no es del cliente. | Descarta el lead. |
| **Venta cerrada** | El cliente contrató. | Pide **tipo de visa y valor**, registra la venta para las comisiones (CALLFLOW) y cierra el lead. |

Puede agregar una nota corta en cada resultado, por ejemplo "prefiere que lo llamen en la tarde".

### 4. Mantenga la ficha al día

- **Datos del caso:** tipo de visa y país de interés. Elija una sugerencia o escriba otro valor.
- **Etapa:** muévala a medida que avanza el trámite (en contacto → en asesoría → documentos → pago → cita agendada). Para **descartar** un lead hay que elegir el motivo.
- **Agendar llamada:** sirve para dejar programada la próxima llamada sin haber llamado todavía, por ejemplo si el cliente pidió por WhatsApp que lo llamen mañana.
- **Notas internas:** solo las ve el equipo, nunca el cliente. No se pueden borrar: escriba con cuidado.

### 5. Si el cliente vuelve a escribir

Le llega a usted, que ya conoce su caso, aunque esté en pausa. Si usted ya no está en la empresa, pasa a otro asesor.

---

## Supervisor

### Asesores

En **Asesores** ve el estado de todo el equipo y cuántos leads abiertos tiene cada uno, y puede cambiarle el estado a cualquier asesor (por ejemplo, poner en pausa a alguien que se fue sin marcar).

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
- el detalle por asesor.

---

## Administrador

- **Usuarios:** crear cuentas (asesor, supervisor o administrador), asignar a cada asesor su número de WhatsApp y su código de CALLFLOW, cambiar contraseñas y desactivar a quien deja la empresa. Un usuario desactivado no puede ingresar, y sus leads pasan a otros asesores cuando el cliente vuelve a escribir o cuando se reasignan.
- **Configuración:** horario de atención, intentos por asesor, minutos para la primera llamada, minutos entre reintentos, minutos para alertar al supervisor y textos automáticos de WhatsApp (bienvenida, fuera de horario y aviso de privacidad). Los cambios rigen de inmediato.

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
