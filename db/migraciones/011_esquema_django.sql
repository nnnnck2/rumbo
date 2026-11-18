-- 011 · Esquema para las tablas propias de Django (SCRUM-14)
-- auth, sesiones, admin y contenttypes viven aquí, separadas del negocio (esquema rumbo).
-- Las crea `python manage.py migrate` conectado como rumbo_app, que es dueño solo de
-- lo que cree dentro de este esquema. Django se conecta con search_path = django, rumbo.

CREATE SCHEMA django AUTHORIZATION rumbo_owner;
REVOKE ALL ON SCHEMA django FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA django TO rumbo_app;
