#!/usr/bin/env bash
# PostgreSQL health check — run any time to verify the database is healthy.
# Run as: sudo bash 08_healthcheck.sh
#
# Reads DB_NAME, DB_USER, DB_PASS from DATABASE_URL in /etc/zerodha-mcp/.env
# so it works regardless of what username/database was chosen at setup time.
set -euo pipefail

ENV_FILE="/etc/zerodha-mcp/.env"

# Parse DATABASE_URL — format: postgresql[+asyncpg]://user:pass@host:port/dbname
if [ -f "${ENV_FILE}" ]; then
  _URL=$(grep '^DATABASE_URL=' "${ENV_FILE}" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
else
  _URL="${DATABASE_URL:-}"
fi

if [ -z "${_URL}" ]; then
  echo "ERROR: DATABASE_URL not found in ${ENV_FILE}"
  exit 1
fi

# Strip driver prefix
_URL=$(echo "${_URL}" | sed 's|postgresql+asyncpg://|postgresql://|')

DB_USER=$(echo "${_URL}" | sed 's|postgresql://\([^:]*\):.*|\1|')
DB_PASS=$(echo "${_URL}" | sed 's|postgresql://[^:]*:\([^@]*\)@.*|\1|')
DB_HOST=$(echo "${_URL}" | sed 's|.*@\([^:/]*\).*|\1|')
DB_PORT=$(echo "${_URL}" | sed 's|.*:\([0-9]*\)/.*|\1|')
DB_NAME=$(echo "${_URL}" | sed 's|.*/\([^?]*\).*|\1|')

PASS=0
FAIL=0

check() {
  local label="$1"
  local result="$2"
  local ok="${3:-}"

  if [ -n "${ok}" ] && [ "${result}" = "${ok}" ]; then
    echo "  [OK]  ${label}"
    PASS=$((PASS + 1))
  elif [ -z "${ok}" ] && [ -n "${result}" ]; then
    echo "  [OK]  ${label}: ${result}"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] ${label}: got '${result}', expected '${ok}'"
    FAIL=$((FAIL + 1))
  fi
}

echo "============================================================"
echo " PostgreSQL Health Check — $(date '+%Y-%m-%d %H:%M:%S IST')"
echo " DB: ${DB_NAME}  User: ${DB_USER}  Host: ${DB_HOST}:${DB_PORT}"
echo "============================================================"

echo ""
echo "--- Service ---"
if systemctl is-active --quiet postgresql; then
  echo "  [OK]  postgresql.service is active"
  PASS=$((PASS + 1))
else
  echo "  [FAIL] postgresql.service is NOT active"
  FAIL=$((FAIL + 1))
fi

if systemctl is-enabled --quiet backup_postgres.timer 2>/dev/null; then
  echo "  [OK]  backup_postgres.timer is enabled"
  PASS=$((PASS + 1))
else
  echo "  [WARN] backup_postgres.timer is NOT enabled (run sudo bash infra/07_setup_systemd_timer.sh)"
fi

echo ""
echo "--- Connectivity ---"
PG_VERSION=$(sudo -u postgres psql -tAc "SELECT version();" 2>/dev/null | head -1 || echo "")
check "superuser psql (Unix socket)" "${PG_VERSION}"

APP_VERSION=$(PGPASSWORD="${DB_PASS}" psql -w -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
  -tAc "SELECT version();" 2>/dev/null | head -1 || echo "")
check "${DB_USER} TCP ${DB_HOST}:${DB_PORT}" "${APP_VERSION}"

echo ""
echo "--- Configuration ---"
LISTEN=$(sudo -u postgres psql -tAc "SHOW listen_addresses;" | tr -d ' ')
check "listen_addresses" "${LISTEN}" "localhost"

SEARCH=$(sudo -u postgres psql -d "${DB_NAME}" -tAc "SHOW search_path;" | tr -d ' ')
check "search_path" "${SEARCH}" "zerodha,public"

SB=$(sudo -u postgres psql -tAc "SHOW shared_buffers;" | tr -d ' ')
check "shared_buffers" "${SB}" "2GB"

echo ""
echo "--- Database ---"
DB_EXISTS=$(sudo -u postgres psql -tAc "SELECT datname FROM pg_database WHERE datname='${DB_NAME}';" | tr -d ' ')
check "database ${DB_NAME} exists" "${DB_EXISTS}" "${DB_NAME}"

USER_EXISTS=$(sudo -u postgres psql -tAc "SELECT rolname FROM pg_roles WHERE rolname='${DB_USER}';" | tr -d ' ')
check "role ${DB_USER} exists" "${USER_EXISTS}" "${DB_USER}"

SCHEMAS=$(sudo -u postgres psql -d "${DB_NAME}" -tAc \
  "SELECT string_agg(nspname, ',' ORDER BY nspname) FROM pg_namespace WHERE nspname IN ('zerodha','migration','public');" | tr -d ' ')
check "bootstrap schemas (migration,public,zerodha)" "${SCHEMAS}" "migration,public,zerodha"

ALEMBIC_SCHEMAS=$(sudo -u postgres psql -d "${DB_NAME}" -tAc \
  "SELECT string_agg(nspname, ',' ORDER BY nspname) FROM pg_namespace WHERE nspname IN ('auth','journal');" | tr -d ' ')
if [ -n "${ALEMBIC_SCHEMAS}" ]; then
  check "alembic schemas (auth,journal)" "${ALEMBIC_SCHEMAS}" "auth,journal"
else
  echo "  [INFO] auth,journal schemas not yet created — run alembic upgrade head first"
fi

EXTENSIONS=$(sudo -u postgres psql -d "${DB_NAME}" -tAc \
  "SELECT string_agg(extname, ',' ORDER BY extname) FROM pg_extension WHERE extname IN ('pg_stat_statements','pgcrypto','uuid-ossp');" | tr -d ' ')
check "extensions (pg_stat_statements,pgcrypto,uuid-ossp)" "${EXTENSIONS}" "pg_stat_statements,pgcrypto,uuid-ossp"

echo ""
echo "--- Active Connections ---"
sudo -u postgres psql -c \
  "SELECT count(*) AS total, state FROM pg_stat_activity GROUP BY state ORDER BY state;" 2>/dev/null

echo ""
echo "--- Database Sizes ---"
sudo -u postgres psql -c \
  "SELECT datname, pg_size_pretty(pg_database_size(datname)) AS size FROM pg_database ORDER BY pg_database_size(datname) DESC;" 2>/dev/null

echo ""
echo "--- Backups ---"
BACKUP_DIR="/var/backups/postgresql"
LATEST=$(ls -t "${BACKUP_DIR}/${DB_NAME}_"*.sql.gz 2>/dev/null | head -1 || echo "")
if [ -n "${LATEST}" ]; then
  BACKUP_AGE=$(( ($(date +%s) - $(stat -c %Y "${LATEST}")) / 3600 ))
  echo "  Latest backup : ${LATEST}"
  echo "  Age           : ${BACKUP_AGE} hours ago"
  if [ "${BACKUP_AGE}" -le 25 ]; then
    echo "  [OK]  Backup is recent (within 25 hours)"
    PASS=$((PASS + 1))
  else
    echo "  [WARN] Backup is ${BACKUP_AGE}h old — check backup_postgres.timer"
    FAIL=$((FAIL + 1))
  fi
  echo "  Count         : $(ls "${BACKUP_DIR}/${DB_NAME}_"*.sql.gz 2>/dev/null | wc -l) file(s)"
else
  echo "  [WARN] No backups found in ${BACKUP_DIR} (expected after first backup timer run)"
fi

echo ""
echo "--- Top Slow Queries (pg_stat_statements) ---"
sudo -u postgres psql -d "${DB_NAME}" -c \
  "SELECT left(query,80) AS query, calls, round(mean_exec_time::numeric,1) AS mean_ms
   FROM pg_stat_statements
   ORDER BY total_exec_time DESC
   LIMIT 5;" 2>/dev/null || echo "  (pg_stat_statements not yet populated)"

echo ""
echo "============================================================"
echo " Result: ${PASS} passed, ${FAIL} failed"
echo "============================================================"

[ "${FAIL}" -eq 0 ] || exit 1
