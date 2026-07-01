#!/usr/bin/env bash
# Daily backup script — reads DB_NAME from DATABASE_URL in /etc/zerodha-mcp/.env
# Called by backup_postgres.service (systemd timer). Can also be run manually:
#   sudo bash infra/05_backup.sh
set -euo pipefail

ENV_FILE="/etc/zerodha-mcp/.env"
BACKUP_DIR="/var/backups/postgresql"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
KEEP_DAYS=30

# Parse DB_NAME from DATABASE_URL
_URL=""
if [ -f "${ENV_FILE}" ]; then
  _URL=$(grep '^DATABASE_URL=' "${ENV_FILE}" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
fi
if [ -z "${_URL}" ]; then
  echo "ERROR: DATABASE_URL not found in ${ENV_FILE}" >&2
  exit 1
fi
DB_NAME=$(echo "${_URL}" | sed 's|.*//[^/]*/\([^?]*\).*|\1|')

BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.sql.gz"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting backup of ${DB_NAME}..."

mkdir -p "${BACKUP_DIR}"
chown postgres:postgres "${BACKUP_DIR}"

sudo -u postgres pg_dump "${DB_NAME}" | gzip > "${BACKUP_FILE}"

if [ ! -s "${BACKUP_FILE}" ]; then
  echo "ERROR: Backup file is empty — pg_dump may have failed: ${BACKUP_FILE}" >&2
  rm -f "${BACKUP_FILE}"
  exit 1
fi

SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup created: ${BACKUP_FILE} (${SIZE})"

DELETED=$(find "${BACKUP_DIR}" -name "${DB_NAME}_*.sql.gz" -mtime "+${KEEP_DAYS}" -print -delete | wc -l)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Removed ${DELETED} backup(s) older than ${KEEP_DAYS} days."

echo ""
echo "Retained backups:"
ls -lh "${BACKUP_DIR}/${DB_NAME}_"*.sql.gz 2>/dev/null || echo "  (none)"
