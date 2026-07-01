#!/usr/bin/env bash
# Fix an existing PostgreSQL installation that was not set up by our scripts.
# Safe to run on a live database — no data is modified.
#
# Reads DB_NAME, DB_USER, DB_PASS from DATABASE_URL in /etc/zerodha-mcp/.env
#
# Fixes:
#   1. postgresql.conf — shared_buffers, pg_stat_statements, timezone, etc.
#   2. pg_hba.conf    — correct auth methods for TCP localhost
#   3. Extensions     — pgcrypto, uuid-ossp, pg_stat_statements
#   4. search_path    — set per-database default to zerodha,public
#   5. Role           — create DB_USER if missing, set password from DATABASE_URL
#   6. Grants         — schema + table grants for DB_USER
#
# Run as: sudo bash infra/09_fix_existing_postgres.sh
set -euo pipefail

ENV_FILE="/etc/zerodha-mcp/.env"

# ---------------------------------------------------------------------------
# Parse DATABASE_URL
# ---------------------------------------------------------------------------
if [ -f "${ENV_FILE}" ]; then
  _URL=$(grep '^DATABASE_URL=' "${ENV_FILE}" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
else
  _URL="${DATABASE_URL:-}"
fi

if [ -z "${_URL}" ]; then
  echo "ERROR: DATABASE_URL not found in ${ENV_FILE}"
  echo "Run: sudo bash infra/env/setup_env.sh"
  exit 1
fi

_URL=$(echo "${_URL}" | sed 's|postgresql+asyncpg://|postgresql://|')
DB_USER=$(echo "${_URL}" | sed 's|postgresql://\([^:]*\):.*|\1|')
DB_PASS=$(echo "${_URL}" | sed 's|postgresql://[^:]*:\([^@]*\)@.*|\1|')
DB_NAME=$(echo "${_URL}" | sed 's|.*/\([^?]*\).*|\1|')

echo "==> Using: user=${DB_USER}  db=${DB_NAME}"

# ---------------------------------------------------------------------------
# Auto-detect PostgreSQL version
# ---------------------------------------------------------------------------
PG_VERSION=$(pg_lsclusters --no-header 2>/dev/null | awk '{print $1}' | sort -rn | head -1)
if [ -z "${PG_VERSION}" ]; then
  echo "ERROR: Could not detect PostgreSQL version."
  exit 1
fi
echo "==> PostgreSQL ${PG_VERSION} detected"

PG_CONF="/etc/postgresql/${PG_VERSION}/main/postgresql.conf"
PG_HBA="/etc/postgresql/${PG_VERSION}/main/pg_hba.conf"

# ---------------------------------------------------------------------------
# 1. postgresql.conf — patch in-place
# ---------------------------------------------------------------------------
echo ""
echo "==> Patching postgresql.conf..."
cp "${PG_CONF}" "${PG_CONF}.bak.$(date +%Y%m%d_%H%M%S)"

patch_conf() {
  local key="$1"
  local value="$2"
  sed -i "/^#*\s*${key}\s*=/d" "${PG_CONF}"
  echo "${key} = ${value}" >> "${PG_CONF}"
}

patch_conf "listen_addresses"                "'localhost'"
patch_conf "shared_buffers"                  "2GB"
patch_conf "effective_cache_size"            "8GB"
patch_conf "work_mem"                        "16MB"
patch_conf "maintenance_work_mem"            "512MB"
patch_conf "wal_buffers"                     "32MB"
patch_conf "checkpoint_completion_target"    "0.9"
patch_conf "shared_preload_libraries"        "'pg_stat_statements'"
patch_conf "pg_stat_statements.track"        "all"
patch_conf "max_worker_processes"            "4"
patch_conf "max_parallel_workers_per_gather" "2"
patch_conf "max_parallel_workers"            "4"
patch_conf "log_min_duration_statement"      "1000"
patch_conf "timezone"                        "'Asia/Kolkata'"
patch_conf "log_timezone"                    "'Asia/Kolkata'"

echo "  postgresql.conf patched."

# ---------------------------------------------------------------------------
# 2. pg_hba.conf
# ---------------------------------------------------------------------------
echo ""
echo "==> Writing pg_hba.conf..."
cp "${PG_HBA}" "${PG_HBA}.bak.$(date +%Y%m%d_%H%M%S)"

cat > "${PG_HBA}" << 'EOF'
# PostgreSQL Client Authentication Configuration
# Localhost and Unix socket only — port 5432 is never exposed to the internet.

# TYPE  DATABASE        USER            ADDRESS                 METHOD

# Unix socket — postgres superuser via peer auth (no password needed locally)
local   all             postgres                                peer

# Unix socket — all other users via md5
local   all             all                                     md5

# TCP localhost — application connections
host    all             all             127.0.0.1/32            scram-sha-256

# TCP IPv6 localhost
host    all             all             ::1/128                 scram-sha-256
EOF

echo "  pg_hba.conf written."

# ---------------------------------------------------------------------------
# 3. Restart to pick up shared_preload_libraries
# ---------------------------------------------------------------------------
echo ""
echo "==> Restarting PostgreSQL..."
systemctl restart postgresql
sleep 2
echo "  PostgreSQL restarted."

# ---------------------------------------------------------------------------
# 4. Role, extensions, search_path, grants
# ---------------------------------------------------------------------------
echo ""
echo "==> Applying database-level fixes..."

sudo -u postgres psql -v db_user="${DB_USER}" -v db_pass="${DB_PASS}" -v db_name="${DB_NAME}" << 'SQLEOF'
-- Create role if missing, set password — use psql variables to keep
-- the password out of pg_stat_statements query text
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'db_user') THEN
    EXECUTE format('CREATE USER %I WITH PASSWORD %L', :'db_user', :'db_pass');
    RAISE NOTICE 'Created role %', :'db_user';
  ELSE
    EXECUTE format('ALTER USER %I WITH PASSWORD %L', :'db_user', :'db_pass');
    RAISE NOTICE 'Updated password for %', :'db_user';
  END IF;
END
$$;

GRANT ALL PRIVILEGES ON DATABASE :db_name TO :db_user;
SQLEOF

sudo -u postgres psql -d "${DB_NAME}" << SQLEOF
-- Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- search_path
ALTER DATABASE ${DB_NAME} SET search_path TO zerodha, public;

-- Schema grants (schemas that exist now)
GRANT ALL ON SCHEMA public    TO ${DB_USER};
GRANT ALL ON SCHEMA zerodha   TO ${DB_USER};
GRANT ALL ON SCHEMA migration TO ${DB_USER};

DO \$\$
BEGIN
  IF EXISTS (SELECT FROM pg_namespace WHERE nspname = 'journal') THEN
    EXECUTE 'GRANT ALL ON SCHEMA journal TO ${DB_USER}';
  END IF;
  IF EXISTS (SELECT FROM pg_namespace WHERE nspname = 'auth') THEN
    EXECUTE 'GRANT ALL ON SCHEMA auth TO ${DB_USER}';
  END IF;
  IF EXISTS (SELECT FROM pg_namespace WHERE nspname = 'audit') THEN
    EXECUTE 'GRANT ALL ON SCHEMA audit TO ${DB_USER}';
  END IF;
END
\$\$;

-- Table grants on existing tables
GRANT ALL ON ALL TABLES IN SCHEMA zerodha   TO ${DB_USER};
GRANT ALL ON ALL TABLES IN SCHEMA migration TO ${DB_USER};
GRANT ALL ON ALL TABLES IN SCHEMA public    TO ${DB_USER};

-- Default privileges for future tables created by this role
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_USER} IN SCHEMA zerodha   GRANT ALL ON TABLES    TO ${DB_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_USER} IN SCHEMA zerodha   GRANT ALL ON SEQUENCES TO ${DB_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_USER} IN SCHEMA journal   GRANT ALL ON TABLES    TO ${DB_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_USER} IN SCHEMA journal   GRANT ALL ON SEQUENCES TO ${DB_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_USER} IN SCHEMA auth      GRANT ALL ON TABLES    TO ${DB_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_USER} IN SCHEMA auth      GRANT ALL ON SEQUENCES TO ${DB_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_USER} IN SCHEMA migration GRANT ALL ON TABLES    TO ${DB_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_USER} IN SCHEMA migration GRANT ALL ON SEQUENCES TO ${DB_USER};
SQLEOF

echo "  Database-level fixes applied."

# ---------------------------------------------------------------------------
# 5. Verify
# ---------------------------------------------------------------------------
echo ""
echo "==> Verification:"
sudo -u postgres psql -tAc "SHOW shared_buffers;"              | xargs echo "  shared_buffers   :"
sudo -u postgres psql -tAc "SHOW listen_addresses;"            | xargs echo "  listen_addresses :"
sudo -u postgres psql -d "${DB_NAME}" -tAc "SHOW search_path;" | xargs echo "  search_path      :"
sudo -u postgres psql -tAc "SELECT rolname FROM pg_roles WHERE rolname='${DB_USER}';" | xargs echo "  role             :"
sudo -u postgres psql -d "${DB_NAME}" -tAc \
  "SELECT string_agg(extname, ', ' ORDER BY extname) FROM pg_extension WHERE extname IN ('pgcrypto','uuid-ossp','pg_stat_statements');" \
  | xargs echo "  extensions       :"

echo ""
echo "Done. Run: sudo bash infra/08_healthcheck.sh"
