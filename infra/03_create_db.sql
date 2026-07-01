-- =============================================================================
-- PostgreSQL 17 — Zerodha MCP database bootstrap
-- Run as: sudo -u postgres psql -f 03_create_db.sql
--
-- IMPORTANT: Set DB_PASSWORD before running:
--   sudo -u postgres psql \
--     -v db_password='your_strong_password_here' \
--     -f 03_create_db.sql
-- =============================================================================

\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------------
-- 1. Application user
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'zerodha_app') THEN
    CREATE USER zerodha_app WITH PASSWORD :'db_password';
    RAISE NOTICE 'Created user zerodha_app';
  ELSE
    ALTER USER zerodha_app WITH PASSWORD :'db_password';
    RAISE NOTICE 'Updated password for existing user zerodha_app';
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. Database
-- ---------------------------------------------------------------------------
SELECT 'CREATE DATABASE zerodha_mcp OWNER zerodha_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'zerodha_mcp') \gexec

GRANT ALL PRIVILEGES ON DATABASE zerodha_mcp TO zerodha_app;

-- ---------------------------------------------------------------------------
-- 3. Connect to the new database for the rest of the setup
-- ---------------------------------------------------------------------------
\c zerodha_mcp

-- ---------------------------------------------------------------------------
-- 4. Extensions (must be created by superuser)
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- ---------------------------------------------------------------------------
-- 5. Schemas
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS zerodha;
CREATE SCHEMA IF NOT EXISTS migration;

GRANT ALL ON SCHEMA zerodha   TO zerodha_app;
GRANT ALL ON SCHEMA migration TO zerodha_app;
GRANT ALL ON SCHEMA public    TO zerodha_app;

-- ---------------------------------------------------------------------------
-- 6. Default search path — zerodha schema is the default for app tables
-- ---------------------------------------------------------------------------
ALTER DATABASE zerodha_mcp SET search_path TO zerodha, public;

-- ---------------------------------------------------------------------------
-- 7. Default privileges FOR ROLE zerodha_app
--    This ensures Alembic migrations (which run as zerodha_app) automatically
--    receive full access to any tables/sequences they create.
-- ---------------------------------------------------------------------------
ALTER DEFAULT PRIVILEGES FOR ROLE zerodha_app
  IN SCHEMA zerodha
  GRANT ALL ON TABLES TO zerodha_app;

ALTER DEFAULT PRIVILEGES FOR ROLE zerodha_app
  IN SCHEMA zerodha
  GRANT ALL ON SEQUENCES TO zerodha_app;

ALTER DEFAULT PRIVILEGES FOR ROLE zerodha_app
  IN SCHEMA migration
  GRANT ALL ON TABLES TO zerodha_app;

ALTER DEFAULT PRIVILEGES FOR ROLE zerodha_app
  IN SCHEMA migration
  GRANT ALL ON SEQUENCES TO zerodha_app;

ALTER DEFAULT PRIVILEGES FOR ROLE zerodha_app
  IN SCHEMA public
  GRANT ALL ON TABLES TO zerodha_app;

ALTER DEFAULT PRIVILEGES FOR ROLE zerodha_app
  IN SCHEMA public
  GRANT ALL ON SEQUENCES TO zerodha_app;

-- ---------------------------------------------------------------------------
-- 8. Verification
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Schemas ==='
\dn

\echo ''
\echo '=== Extensions ==='
\dx

\echo ''
\echo '=== Roles ==='
\du

\echo ''
\echo '=== Databases ==='
\l

\echo ''
\echo '=== search_path ==='
SHOW search_path;

\echo ''
\echo 'Database bootstrap complete.'
