#!/usr/bin/env bash
# PostgreSQL health check — run any time to verify the database is healthy.
# Run as: sudo bash 08_healthcheck.sh
set -euo pipefail

DB_NAME="zerodha_mcp"
DB_USER="zerodha_app"
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

if systemctl is-enabled --quiet backup_postgres.timer; then
  echo "  [OK]  backup_postgres.timer is enabled"
  PASS=$((PASS + 1))
else
  echo "  [FAIL] backup_postgres.timer is NOT enabled"
  FAIL=$((FAIL + 1))
fi

echo ""
echo "--- Connectivity ---"
PG_VERSION=$(sudo -u postgres psql -tAc "SELECT version();" 2>/dev/null | head -1 || echo "")
check "superuser psql (Unix socket)" "${PG_VERSION}"

APP_VERSION=$(psql -h 127.0.0.1 -U "${DB_USER}" -d "${DB_NAME}" -tAc "SELECT version();" 2>/dev/null | head -1 || echo "")
check "zerodha_app TCP localhost" "${APP_VERSION}"

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

SCHEMAS=$(sudo -u postgres psql -d "${DB_NAME}" -tAc \
  "SELECT string_agg(nspname, ',' ORDER BY nspname) FROM pg_namespace WHERE nspname IN ('zerodha','migration','public');" | tr -d ' ')
check "schemas (migration,public,zerodha)" "${SCHEMAS}" "migration,public,zerodha"

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
  echo "  [WARN] No backups found in ${BACKUP_DIR}"
  FAIL=$((FAIL + 1))
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
