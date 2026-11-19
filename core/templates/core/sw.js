{% load static %}// SCRUM-122 · Service worker de Rumbo: notificaciones push y app instalable.
// No guarda páginas en caché: Rumbo siempre muestra datos al día (y con datos personales, mejor no dejarlos).
"use strict";

self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (event) { event.waitUntil(self.clients.claim()); });

self.addEventListener("push", function (event) {
  let datos = {};
  try { datos = event.data ? event.data.json() : {}; } catch (e) { datos = { titulo: "Rumbo", mensaje: event.data && event.data.text() }; }
  event.waitUntil(self.registration.showNotification(datos.titulo || "Rumbo", {
    body: datos.mensaje || "",
    icon: "{% static 'img/icono-192.png' %}",
    badge: "{% static 'img/icono-192.png' %}",
    tag: datos.url || "rumbo",
    renotify: true,
    data: { url: datos.url || "/notificaciones/" },
  }));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  const destino = new URL(event.notification.data.url, self.location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (ventanas) {
    for (const v of ventanas) {
      if (new URL(v.url).origin === self.location.origin) { v.focus(); return v.navigate(destino); }
    }
    return self.clients.openWindow(destino);
  }));
});
