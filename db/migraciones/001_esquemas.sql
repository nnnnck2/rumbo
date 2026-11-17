-- 001 · Esquemas y privilegios por defecto
-- Se ejecuta como rumbo_migrator, que entra con ROLE rumbo_owner (dueño de todos los objetos).

-- rumbo      → datos del negocio
-- auditoria  → registro inmutable de cambios
-- api        → vistas de solo lectura para CALLFLOW
CREATE SCHEMA rumbo     AUTHORIZATION rumbo_owner;
CREATE SCHEMA auditoria AUTHORIZATION rumbo_owner;
CREATE SCHEMA api       AUTHORIZATION rumbo_owner;

REVOKE ALL ON SCHEMA rumbo, auditoria, api FROM PUBLIC;

-- Por defecto PostgreSQL deja ejecutar cualquier función a PUBLIC.
-- Aquí nada se ejecuta si no se otorga explícitamente (ver 009_permisos.sql).
ALTER DEFAULT PRIVILEGES FOR ROLE rumbo_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE rumbo_owner REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE rumbo_owner REVOKE ALL ON SEQUENCES FROM PUBLIC;
