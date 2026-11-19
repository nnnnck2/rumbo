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
    avisos.forEach(function (el) {
      el.dataset.listo = "1";
      avisoDelNavegador(el);
      if (!el.dataset.fijo) setTimeout(function () { if (el.isConnected) cerrar(el); }, DURACION_MS);
    });
    // Como mucho 4 en pantalla: se van los más viejos.
    const todos = contenedor.querySelectorAll(".aviso-flotante");
    for (let i = 0; i < todos.length - 4; i++) cerrar(todos[i]);
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
