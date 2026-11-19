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
