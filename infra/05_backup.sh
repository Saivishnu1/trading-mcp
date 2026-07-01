#!/usr/bin/env bash
# Daily backup script for zerodha_mcp database.
# Produces a compressed pg_dump, retains 30 days of history.
#
# Called by backup_postgres.service (systemd timer) — not meant for direct cron.
# Can also be run manually: sudo bash 05_backup.sh
set -euo pipefail

BACKUP_DIR="/var/backups/postgresql"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DB_NAME="zerodha_mcp"
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.sql.gz"
KEEP_DAYS=30

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting backup of ${DB_NAME}..."

# Ensure backup directory exists with correct ownership
mkdir -p "${BACKUP_DIR}"
chown postgres:postgres "${BACKUP_DIR}"

# Compressed dump
sudo -u postgres pg_dump "${DB_NAME}" | gzip > "${BACKUP_FILE}"

# Fail loudly if the file is empty (pg_dump silently failed)
if [ ! -s "${BACKUP_FILE}" ]; then
  echo "ERROR: Backup file is empty — pg_dump may have failed: ${BACKUP_FILE}" >&2
  rm -f "${BACKUP_FILE}"
  exit 1
fi

SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup created: ${BACKUP_FILE} (${SIZE})"

# Remove backups older than KEEP_DAYS
DELETED=$(find "${BACKUP_DIR}" -name "${DB_NAME}_*.sql.gz" -mtime "+${KEEP_DAYS}" -print -delete | wc -l)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Removed ${DELETED} backup(s) older than ${KEEP_DAYS} days."

echo ""
echo "Retained backups:"
ls -lh "${BACKUP_DIR}/${DB_NAME}_"*.sql.gz 2>/dev/null || echo "  (none)"
