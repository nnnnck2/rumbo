// SCRUM-78 · Recordar registrar la llamada.
// Al tocar "Llamar" se guarda (solo en este navegador) a quién se llamó. Al volver a Rumbo:
//   · en la ficha de ese cliente se abre "¿Cómo le fue con …?";
//   · en cualquier otra pantalla aparece un aviso "Falta registrar la llamada a …".
// Se borra al registrar el resultado, al tocar "Ahora no" o a las 3 horas.
(function () {
  "use strict";
  const CLAVE = "rumbo-llamada";
  const VIGENCIA_MS = 3 * 60 * 60 * 1000;
  let salioDeLaPagina = false;

  function leer() {
    try {
      const v = JSON.parse(localStorage.getItem(CLAVE) || "null");
      if (v && Date.now() - v.t < VIGENCIA_MS) return v;
      localStorage.removeItem(CLAVE);
    } catch (e) { /* almacenamiento bloqueado: sin recordatorio */ }
    return null;
  }
  function guardar(v) { try { localStorage.setItem(CLAVE, JSON.stringify(v)); } catch (e) {} }
  function borrar() { try { localStorage.removeItem(CLAVE); } catch (e) {} ocultarAviso(); }

  function modalDe(lead) {
    const m = document.getElementById("modal-como-le-fue");
    return m && m.dataset.lead === String(lead) ? m : null;
  }
  function abrirModal(lead) {
    const m = modalDe(lead);
    if (m && window.bootstrap) bootstrap.Modal.getOrCreateInstance(m).show();
    return !!m;
  }

  function ocultarAviso() {
    const aviso = document.getElementById("aviso-llamada");
    if (aviso) aviso.hidden = true;
  }
  function mostrarAviso(v) {
    const aviso = document.getElementById("aviso-llamada");
    if (!aviso) return;
    aviso.querySelector("[data-nombre]").textContent = v.nombre;   // texto, nunca HTML
    aviso.querySelector("a").href = v.url;
    aviso.hidden = false;
  }

  // Al tocar "Llamar"
  document.addEventListener("click", function (ev) {
    const llamar = ev.target.closest("[data-llamar]");
    if (llamar) {
      guardar({ lead: llamar.dataset.llamar, nombre: llamar.dataset.nombre, url: llamar.dataset.url, t: Date.now() });
      salioDeLaPagina = false;
      return;
    }
    // Botones de la ventana: tocan el botón real del formulario (misma lógica: confirmar, agenda, venta).
    const proxy = ev.target.closest("[data-proxy]");
    if (proxy) {
      const m = proxy.closest(".modal");
      const real = document.querySelector('#form-intento .boton-resultado[data-codigo="' + proxy.dataset.proxy + '"]');
      bootstrap.Modal.getOrCreateInstance(m).hide();
      if (real) {
        if (real.dataset.tipo !== "directo") document.getElementById("tarjeta-resultado").scrollIntoView({ behavior: "smooth", block: "start" });
        real.click();
      }
      return;
    }
    if (ev.target.closest("[data-ahora-no]")) {
      borrar();
      const m = ev.target.closest(".modal");
      if (m) bootstrap.Modal.getOrCreateInstance(m).hide();
    }
  });

  // Al guardar un resultado de ese cliente, ya no hay nada pendiente.
  document.addEventListener("submit", function (ev) {
    const form = ev.target;
    const v = leer();
    if (form.id === "form-intento" && v && form.dataset.lead === String(v.lead)) borrar();
  }, true);

  // Al volver de la app de teléfono (la página estuvo oculta).
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") { salioDeLaPagina = true; return; }
    const v = leer();
    if (!v || !salioDeLaPagina) return;
    salioDeLaPagina = false;
    if (!abrirModal(v.lead)) mostrarAviso(v);
  });

  // Al cargar cualquier pantalla con una llamada sin registrar.
  function revisar() {
    const v = leer();
    if (!v) return;
    if (document.querySelector('[data-sin-registro="' + v.lead + '"]')) { borrar(); return; }  // ya cerrado o en cola
    if (modalDe(v.lead)) { ocultarAviso(); return; }   // está en la ficha: la tarjeta de resultado está a la vista
    mostrarAviso(v);
  }
  document.addEventListener("DOMContentLoaded", revisar);
  document.addEventListener("htmx:afterSettle", revisar);
})();

// 017 · Notificaciones como CALLFLOW: avisos flotantes (esquina inferior), sonido y aviso del
// navegador cuando Rumbo no está a la vista. Los avisos nuevos llegan por HTMX (core/_contadores.html).
(function () {
  "use strict";
  const CLAVE_SONIDO = "rumbo-sonido-avisos";
  const DURACION_MS = 9000;
  const DURACION_CELULAR_MS = 5000;
  const CELULAR = window.matchMedia("(max-width: 575.98px)");
  let audio = null;

  function sonidoActivo() {
    try { return localStorage.getItem(CLAVE_SONIDO) !== "0"; } catch (e) { return true; }
  }
  // Los navegadores solo dejan sonar después de que la persona tocó la página una vez.
  document.addEventListener("pointerdown", function () {
    if (!audio && window.AudioContext) { try { audio = new AudioContext(); } catch (e) {} }
  }, { once: true });
  function sonar() {
    if (!audio || !sonidoActivo()) return;
    const t = audio.currentTime;
    [[880, 0], [1320, 0.14]].forEach(function ([frecuencia, inicio]) {
      const o = audio.createOscillator(), g = audio.createGain();
      o.frequency.value = frecuencia; o.type = "sine";
      g.gain.setValueAtTime(0.0001, t + inicio);
      g.gain.exponentialRampToValueAtTime(0.18, t + inicio + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + inicio + 0.25);
      o.connect(g).connect(audio.destination);
      o.start(t + inicio); o.stop(t + inicio + 0.3);
    });
  }

  function avisoDelNavegador(el) {
    if (!("Notification" in window) || Notification.permission !== "granted" || document.visibilityState === "visible") return;
    const n = new Notification(el.dataset.titulo, { body: el.dataset.mensaje || "", tag: "rumbo-" + el.dataset.aviso });
    n.onclick = function () { window.focus(); location.href = el.dataset.url; n.close(); };
  }

  function cerrar(el) {
    el.classList.add("saliendo");
    setTimeout(function () { el.remove(); }, 250);
  }

  function nuevos(contenedor) {
    const avisos = contenedor.querySelectorAll(".aviso-flotante:not([data-listo])");
    if (!avisos.length) return;
    sonar();
    const celular = CELULAR.matches;
    avisos.forEach(function (el) {
      el.dataset.listo = "1";
      avisoDelNavegador(el);
      // En el celular ninguno queda fijo: se van solos más rápido (siguen en la campana).
      if (celular || !el.dataset.fijo) setTimeout(function () { if (el.isConnected) cerrar(el); }, celular ? DURACION_CELULAR_MS : DURACION_MS);
    });
    // Computadora: como mucho 3 en pantalla. Celular: solo el más nuevo, con "y N más" que lleva a la campana.
    const todos = Array.from(contenedor.querySelectorAll(".aviso-flotante:not(.saliendo)"));
    const maximo = celular ? 1 : 3;
    const sobran = todos.slice(0, Math.max(0, todos.length - maximo));
    sobran.forEach(function (el) { el.remove(); });
    if (celular && sobran.length) {
      const ultimo = todos[todos.length - 1];
      let total = parseInt(ultimo.dataset.mas || "0", 10);
      sobran.forEach(function (el) { total += 1 + parseInt(el.dataset.mas || "0", 10); });
      ultimo.dataset.mas = String(total);
      let mas = ultimo.querySelector(".aviso-mas");
      if (!mas) {
        mas = document.createElement("a");
        mas.className = "aviso-mas";
        mas.href = contenedor.dataset.urlTodas || "/notificaciones/";
        ultimo.insertBefore(mas, ultimo.querySelector("[data-cerrar-aviso]"));
      }
      mas.textContent = "+" + ultimo.dataset.mas;
      mas.setAttribute("aria-label", "Ver " + ultimo.dataset.mas + " avisos más");
    }
  }

  document.addEventListener("click", function (ev) {
    const x = ev.target.closest("[data-cerrar-aviso]");
    if (x) cerrar(x.closest(".aviso-flotante"));
    if (ev.target.closest("[data-activar-avisos]")) {
      Notification.requestPermission().then(pintarEstado);
    }
  });
  document.addEventListener("htmx:oobAfterSwap", function (ev) {
    const c = document.getElementById("avisos-flotantes");
    if (c && (ev.detail.target === c || c.contains(ev.detail.target))) nuevos(c);
  });
  document.addEventListener("htmx:afterSettle", function () {
    const c = document.getElementById("avisos-flotantes");
    if (c) nuevos(c);
    pintarEstado();
  });

  // Estado de los avisos del navegador (panel de la campana y página de notificaciones).
  function pintarEstado() {
    document.querySelectorAll("[data-estado-avisos]").forEach(function (caja) {
      if (!("Notification" in window)) { caja.textContent = "Este navegador no permite avisos del sistema."; return; }
      if (Notification.permission === "granted") {
        caja.innerHTML = '<i class="bi bi-check-circle text-success" aria-hidden="true"></i> Avisos del navegador activados.';
      } else if (Notification.permission === "denied") {
        caja.textContent = "Los avisos del navegador están bloqueados: actívelos en la configuración del sitio (candado de la barra de direcciones).";
      } else {
        caja.innerHTML = '<button type="button" class="btn btn-sm btn-outline-primary" data-activar-avisos>' +
                         '<i class="bi bi-bell" aria-hidden="true"></i> Avisarme aunque esté en otra pestaña</button>';
      }
    });
    document.querySelectorAll("[data-sonido-avisos]").forEach(function (sw) {
      sw.checked = sonidoActivo();
      sw.onchange = function () { try { localStorage.setItem(CLAVE_SONIDO, sw.checked ? "1" : "0"); } catch (e) {} };
    });
  }
  document.addEventListener("DOMContentLoaded", pintarEstado);
})();

// Responsive · tablas apilables: cada celda recibe el título de su columna (data-label) para que,
// en el celular, cada fila se vea como una tarjeta "Etiqueta: valor" en vez de deslizar hacia el costado.
(function () {
  "use strict";
  function etiquetar() {
    document.querySelectorAll("table.tabla-apilable:not([data-etiquetada])").forEach(function (t) {
      const titulos = Array.from(t.querySelectorAll("thead th")).map(function (th) { return th.textContent.trim(); });
      t.querySelectorAll("tbody tr").forEach(function (tr) {
        Array.from(tr.children).forEach(function (td, i) {
          if (td.colSpan > 1) { td.classList.add("celda-completa"); return; }
          if (titulos[i]) td.setAttribute("data-label", titulos[i]);
        });
      });
      t.setAttribute("data-etiquetada", "1");
    });
  }
  document.addEventListener("DOMContentLoaded", etiquetar);
  document.addEventListener("htmx:afterSettle", etiquetar);
})();

// Tablero en el celular: los chips llevan a la columna del asesor, el chip de la columna visible
// queda marcado y el refresco automático (cada 30 s) no devuelve el tablero a la primera columna.
(function () {
  "use strict";
  let posicion = 0;
  function tablero() { return document.querySelector("#tablero .tablero"); }
  function marcar() {
    const t = tablero(); if (!t) return;
    let visible = null;
    t.querySelectorAll(".columna-tablero").forEach(function (c) {
      if (visible === null && c.offsetLeft + c.offsetWidth / 2 > t.scrollLeft) visible = c.id;
    });
    document.querySelectorAll("[data-ir-columna]").forEach(function (b) {
      const activo = b.dataset.irColumna === visible;
      b.classList.toggle("activo", activo);
      if (activo) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
    });
  }
  function preparar() {
    const t = tablero(); if (!t) return;
    t.scrollLeft = posicion;
    t.addEventListener("scroll", function () { posicion = t.scrollLeft; window.requestAnimationFrame(marcar); }, { passive: true });
    marcar();
  }
  document.addEventListener("click", function (e) {
    const b = e.target.closest("[data-ir-columna]"); const t = tablero();
    const c = b && document.getElementById(b.dataset.irColumna);
    if (!c || !t) return;
    t.scrollTo({ left: c.offsetLeft - 16, behavior: "smooth" });
  });
  document.addEventListener("DOMContentLoaded", preparar);
  document.addEventListener("htmx:afterSettle", function (e) { if (e.target.id === "tablero") preparar(); });
})();

// SCRUM-95 / 102 · Hora del cliente con semáforo (verde 9–19, ámbar 8–9 y 19–21, rojo el resto; mismas
// reglas que leads/zonas.py). Se actualiza cada minuto. Si allá es muy temprano o muy tarde, "Llamar"
// pide confirmar antes de abrir el teléfono.
(function () {
  "use strict";
  function horaEn(zona) {
    const partes = new Intl.DateTimeFormat("es-EC", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: zona })
      .formatToParts(new Date());
    const h = parseInt(partes.find(function (p) { return p.type === "hour"; }).value, 10) % 24;
    const m = parseInt(partes.find(function (p) { return p.type === "minute"; }).value, 10);
    return { h: h, m: m, texto: String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0") };
  }
  function tono(h) {
    if (h >= 9 && h < 19) return "verde";
    if (h >= 8 && h < 21) return "ambar";
    return "rojo";
  }
  const TEXTO_TONO = { verde: "buena hora", ambar: "hora límite", rojo: "muy temprano o muy tarde" };

  function actualizar() {
    document.querySelectorAll("[data-zona]").forEach(function (el) {
      let hora;
      try { hora = horaEn(el.dataset.zona); } catch (e) { return; }   // zona desconocida: queda la del servidor
      const t = tono(hora.h);
      el.querySelectorAll("[data-hora]").forEach(function (d) { d.textContent = hora.texto; });
      el.classList.remove("tono-verde", "tono-ambar", "tono-rojo");
      el.classList.add("tono-" + t);
      const texto = el.querySelector("[data-tono-texto]");
      if (texto) texto.textContent = TEXTO_TONO[t];
      if (el.hasAttribute("data-aviso-hora")) el.hidden = t === "verde";
    });
  }
  window.setInterval(actualizar, 60000);
  document.addEventListener("DOMContentLoaded", actualizar);
  document.addEventListener("htmx:afterSettle", actualizar);

  // Fase de captura: corre antes del recordatorio "¿Cómo le fue?" y puede cancelar la llamada.
  document.addEventListener("click", function (ev) {
    const boton = ev.target.closest("[data-zona-llamada]");
    if (!boton) return;
    let hora;
    try { hora = horaEn(boton.dataset.zonaLlamada); } catch (e) { return; }
    if (tono(hora.h) !== "rojo") return;
    if (!window.confirm("Allá son las " + hora.texto + ". ¿Llamar igual?")) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }
  }, true);
})();

// SCRUM-101 · Barra fija de contacto en la ficha: aparece cuando el encabezado sale de la pantalla.
(function () {
  "use strict";
  let observador = null;
  function preparar() {
    if (observador) { observador.disconnect(); observador = null; }
    const barra = document.querySelector("[data-barra-contacto]");
    const encabezado = document.querySelector("[data-encabezado-lead]");
    if (!barra || !encabezado || !("IntersectionObserver" in window)) return;
    observador = new IntersectionObserver(function (entradas) {
      const fuera = !entradas[0].isIntersecting && entradas[0].boundingClientRect.top < 0;
      barra.hidden = !fuera;
      barra.classList.toggle("visible", fuera);
    }, { rootMargin: "-64px 0px 0px 0px" });
    observador.observe(encabezado);
  }
  document.addEventListener("DOMContentLoaded", preparar);
  document.addEventListener("htmx:afterSettle", preparar);
})();

// SCRUM-103 · Guion como lista de chequeo. Las marcas se guardan en este navegador por cliente y se
// borran al registrar el resultado. "¿Cómo le fue?" recuerda los pasos que quedaron sin marcar.
(function () {
  "use strict";
  const PREFIJO = "rumbo-guion-";
  function leer(lead) { try { return JSON.parse(localStorage.getItem(PREFIJO + lead) || "[]"); } catch (e) { return []; } }
  function guardar(lead, marcas) {
    try {
      if (marcas.length) localStorage.setItem(PREFIJO + lead, JSON.stringify(marcas));
      else localStorage.removeItem(PREFIJO + lead);
    } catch (e) {}
  }
  function pintar(guion) {
    const marcas = leer(guion.dataset.guion);
    const casillas = guion.querySelectorAll("[data-paso]");
    casillas.forEach(function (c) { c.checked = marcas.indexOf(c.dataset.paso) !== -1; c.closest("li").classList.toggle("hecho", c.checked); });
    const avance = guion.querySelector("[data-avance-guion]");
    if (avance) avance.textContent = marcas.length + " de " + casillas.length;
  }
  function preparar() { document.querySelectorAll("[data-guion]").forEach(pintar); }
  document.addEventListener("change", function (ev) {
    const casilla = ev.target.closest("[data-paso]");
    if (!casilla) return;
    const guion = casilla.closest("[data-guion]");
    const marcas = Array.from(guion.querySelectorAll("[data-paso]:checked")).map(function (c) { return c.dataset.paso; });
    guardar(guion.dataset.guion, marcas);
    pintar(guion);
  });
  // Al registrar el resultado de la llamada, el guion empieza de cero.
  document.addEventListener("submit", function (ev) {
    if (ev.target.id === "form-intento" && ev.target.dataset.lead) guardar(ev.target.dataset.lead, []);
  }, true);
  // Recordatorio en "¿Cómo le fue?"
  document.addEventListener("show.bs.modal", function (ev) {
    const caja = ev.target.querySelector("[data-recordatorio-guion]");
    const guion = document.querySelector('[data-guion="' + ev.target.dataset.lead + '"]');
    if (!caja || !guion) return;
    const lista = caja.querySelector("[data-pendientes-guion]");
    lista.replaceChildren();
    guion.querySelectorAll("[data-paso]:not(:checked)").forEach(function (c) {
      const li = document.createElement("li");
      li.textContent = c.closest("label").querySelector("span").textContent;   // texto, nunca HTML
      lista.appendChild(li);
    });
    // Solo si empezó a usar el guion en esta llamada (si no marcó nada, no se insiste).
    caja.hidden = !lista.children.length || !leer(guion.dataset.guion).length;
  });
  document.addEventListener("DOMContentLoaded", preparar);
  document.addEventListener("htmx:afterSettle", preparar);
})();

// SCRUM-106 · Celebración al cumplir la meta del día: una sola vez por día y por navegador.
(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    const caja = document.querySelector("[data-celebrar]");
    if (!caja) return;
    const clave = "rumbo-meta-celebrada";
    let ya = null;
    try { ya = localStorage.getItem(clave); } catch (e) {}
    if (ya === caja.dataset.celebrar) return;
    try { localStorage.setItem(clave, caja.dataset.celebrar); } catch (e) {}
    caja.classList.add("celebrando");
    window.setTimeout(function () { caja.classList.remove("celebrando"); }, 2600);
  });
})();

// SCRUM-107 · "Actualizado hace N s" en el panel En vivo (se reinicia con cada refresco HTMX).
(function () {
  "use strict";
  let desde = Date.now();
  function pintar() {
    const el = document.querySelector("[data-actualizado]");
    if (!el) return;
    const s = Math.round((Date.now() - desde) / 1000);
    el.textContent = s < 3 ? "Actualizado recién" : "Actualizado hace " + s + " s";
    el.closest(".actualizado-hace").classList.toggle("atrasado", s > 45);
  }
  document.addEventListener("htmx:afterSettle", function (ev) {
    if (ev.target.id === "en-vivo") { desde = Date.now(); pintar(); }
  });
  window.setInterval(pintar, 1000);
})();

// SCRUM-111 · Pestañas de Configuración. La elegida queda en la URL (#whatsapp); si hubo errores al
// guardar, se abre la primera pestaña que los tiene.
(function () {
  "use strict";
  function mostrar(form, clave, enfocar) {
    const botones = form.querySelectorAll("[data-pestana]");
    if (!form.querySelector('[data-panel="' + clave + '"]')) clave = botones[0].dataset.pestana;
    botones.forEach(function (b) {
      const activa = b.dataset.pestana === clave;
      b.classList.toggle("activa", activa);
      b.setAttribute("aria-selected", activa ? "true" : "false");
      b.tabIndex = activa ? 0 : -1;
      if (activa && enfocar) b.focus();
    });
    form.querySelectorAll("[data-panel]").forEach(function (p) { p.hidden = p.dataset.panel !== clave; });
  }
  document.addEventListener("DOMContentLoaded", function () {
    const form = document.querySelector("[data-pestanas-config]");
    if (!form) return;
    mostrar(form, form.dataset.pestanaInicial || location.hash.slice(1) || "horario");
    form.addEventListener("click", function (ev) {
      const b = ev.target.closest("[data-pestana]");
      if (!b) return;
      mostrar(form, b.dataset.pestana);
      history.replaceState(null, "", "#" + b.dataset.pestana);
    });
    // Flechas izquierda/derecha entre pestañas (patrón de accesibilidad de tablist).
    form.querySelector("[role=tablist]").addEventListener("keydown", function (ev) {
      if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
      const botones = Array.from(form.querySelectorAll("[data-pestana]"));
      const i = botones.findIndex(function (b) { return b.classList.contains("activa"); });
      const siguiente = botones[(i + (ev.key === "ArrowRight" ? 1 : botones.length - 1)) % botones.length];
      mostrar(form, siguiente.dataset.pestana, true);
      history.replaceState(null, "", "#" + siguiente.dataset.pestana);
    });
    // Un campo inválido escondido en otra pestaña: se abre esa pestaña para que el navegador lo muestre.
    form.addEventListener("invalid", function (ev) {
      const panel = ev.target.closest("[data-panel]");
      if (panel && panel.hidden) mostrar(form, panel.dataset.panel);
    }, true);
  });
})();

// SCRUM-112 · Vista previa de los mensajes automáticos de WhatsApp (como en compone respuesta_automatica.py).
(function () {
  "use strict";
  const LIMITE = 4096;
  const EJEMPLO = { "{nombre}": "Ana", "{asesor}": "Carlos", "{proxima_apertura}": "mañana lunes desde las 09:00" };
  function valor(id) { const el = document.getElementById(id); return el ? el.value.trim() : ""; }
  function reemplazar(texto) {
    Object.keys(EJEMPLO).forEach(function (k) { texto = texto.split(k).join(EJEMPLO[k]); });
    return texto;
  }
  function pintar(clave, texto) {
    const burbuja = document.querySelector('[data-vista-previa="' + clave + '"]');
    const contador = document.querySelector('[data-contador="' + clave + '"]');
    if (!burbuja) return;
    burbuja.textContent = texto || "(vacío)";                    // texto, nunca HTML
    burbuja.classList.toggle("vacia", !texto);
    if (contador) {
      contador.textContent = texto.length + " / " + LIMITE + " caracteres";
      contador.classList.toggle("excedido", texto.length > LIMITE);
    }
  }
  function actualizar() {
    const privacidad = valor("id_texto_privacidad");
    const unir = function (t) { return [reemplazar(t), privacidad].filter(Boolean).join("\n\n"); };
    pintar("bienvenida", unir(valor("id_texto_bienvenida")));
    pintar("fuera", unir(valor("id_texto_fuera_horario")));
    const aviso = reemplazar(valor("id_aviso_texto")).replace(/[ \t]+/g, " ").replace(/ +([,.!?])/g, "$1");
    pintar("aviso", aviso);
  }
  document.addEventListener("input", function (ev) {
    if (ev.target.closest("[data-pestanas-config]")) actualizar();
  });
  document.addEventListener("DOMContentLoaded", function () {
    if (document.querySelector("[data-vista-previa]")) actualizar();
  });
})();
