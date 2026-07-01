#!/usr/bin/env bash
# Fix an existing PostgreSQL installation that was not set up by our scripts.
# Safe to run on a live database — no data is modified.
#
# Fixes:
#   1. postgresql.conf — shared_buffers, pg_stat_statements, search_path, timezone
#   2. pg_hba.conf    — correct auth methods for TCP localhost
#   3. Extensions     — pgcrypto, uuid-ossp, pg_stat_statements
#   4. search_path    — set per-database default to zerodha,public
#   5. Default privileges — ensure zerodha_app owns its objects
#
# Run as: sudo bash infra/09_fix_existing_postgres.sh
set -euo pipefail

DB_NAME="zerodha_mcp"
DB_USER="zerodha_app"

# Auto-detect PostgreSQL version
PG_VERSION=$(pg_lsclusters --no-header 2>/dev/null | awk '{print $1}' | sort -rn | head -1)
if [ -z "${PG_VERSION}" ]; then
  echo "ERROR: Could not detect PostgreSQL version."
  exit 1
fi
echo "==> PostgreSQL ${PG_VERSION} detected"

PG_CONF="/etc/postgresql/${PG_VERSION}/main/postgresql.conf"
PG_HBA="/etc/postgresql/${PG_VERSION}/main/pg_hba.conf"

# ---------------------------------------------------------------------------
# 1. postgresql.conf — patch only the settings we care about
# ---------------------------------------------------------------------------
echo ""
echo "==> Patching postgresql.conf..."
cp "${PG_CONF}" "${PG_CONF}.bak.$(date +%Y%m%d_%H%M%S)"

patch_conf() {
  local key="$1"
  local value="$2"
  # Remove existing (including commented-out) line for this key, append new value
  sed -i "/^#*\s*${key}\s*=/d" "${PG_CONF}"
  echo "${key} = ${value}" >> "${PG_CONF}"
}

patch_conf "listen_addresses"              "'localhost'"
patch_conf "shared_buffers"               "2GB"
patch_conf "effective_cache_size"         "8GB"
patch_conf "work_mem"                     "16MB"
patch_conf "maintenance_work_mem"         "512MB"
patch_conf "wal_buffers"                  "32MB"
patch_conf "checkpoint_completion_target" "0.9"
patch_conf "shared_preload_libraries"     "'pg_stat_statements'"
patch_conf "pg_stat_statements.track"     "all"
patch_conf "max_worker_processes"         "4"
patch_conf "max_parallel_workers_per_gather" "2"
patch_conf "max_parallel_workers"         "4"
patch_conf "log_min_duration_statement"   "1000"
patch_conf "timezone"                     "'Asia/Kolkata'"
patch_conf "log_timezone"                 "'Asia/Kolkata'"

echo "  postgresql.conf patched."

# ---------------------------------------------------------------------------
# 2. pg_hba.conf — rewrite auth rules
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

# TCP localhost — FastAPI connections
host    all             all             127.0.0.1/32            scram-sha-256

# TCP IPv6 localhost
host    all             all             ::1/128                 scram-sha-256
EOF

echo "  pg_hba.conf written."

# ---------------------------------------------------------------------------
# 3. Restart to pick up shared_preload_libraries change
# ---------------------------------------------------------------------------
echo ""
echo "==> Restarting PostgreSQL..."
systemctl restart postgresql
sleep 2
echo "  PostgreSQL restarted."

# ---------------------------------------------------------------------------
# 4. Extensions + search_path + default privileges
# ---------------------------------------------------------------------------
echo ""
echo "==> Applying database-level fixes..."
sudo -u postgres psql -d "${DB_NAME}" << SQLEOF
-- Extensions (require superuser)
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- search_path default for the database
ALTER DATABASE ${DB_NAME} SET search_path TO zerodha, public;

-- Default privileges so Alembic-created objects are accessible
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_USER} IN SCHEMA zerodha   GRANT ALL ON TABLES    TO ${DB_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_USER} IN SCHEMA zerodha   GRANT ALL ON SEQUENCES TO ${DB_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_USER} IN SCHEMA journal   GRANT ALL ON TABLES    TO ${DB_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_USER} IN SCHEMA journal   GRANT ALL ON SEQUENCES TO ${DB_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_USER} IN SCHEMA auth      GRANT ALL ON TABLES    TO ${DB_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_USER} IN SCHEMA auth      GRANT ALL ON SEQUENCES TO ${DB_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_USER} IN SCHEMA migration GRANT ALL ON TABLES    TO ${DB_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_USER} IN SCHEMA migration GRANT ALL ON SEQUENCES TO ${DB_USER};

-- Grant on existing schemas
GRANT ALL ON SCHEMA zerodha   TO ${DB_USER};
GRANT ALL ON SCHEMA migration TO ${DB_USER};
GRANT ALL ON SCHEMA public    TO ${DB_USER};
SQLEOF

echo "  Database-level fixes applied."

# ---------------------------------------------------------------------------
# 5. Verify
# ---------------------------------------------------------------------------
echo ""
echo "==> Verification:"
sudo -u postgres psql -tAc "SHOW shared_buffers;"         | xargs echo "  shared_buffers    :"
sudo -u postgres psql -tAc "SHOW listen_addresses;"       | xargs echo "  listen_addresses  :"
sudo -u postgres psql -d "${DB_NAME}" -tAc "SHOW search_path;" | xargs echo "  search_path       :"
sudo -u postgres psql -d "${DB_NAME}" -tAc \
  "SELECT string_agg(extname, ', ' ORDER BY extname) FROM pg_extension WHERE extname IN ('pgcrypto','uuid-ossp','pg_stat_statements');" \
  | xargs echo "  extensions        :"

echo ""
echo "Done. Run: sudo bash infra/08_healthcheck.sh"
