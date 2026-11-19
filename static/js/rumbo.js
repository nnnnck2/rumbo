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
