#!/usr/bin/env bash
# Restores database from a pg_dump backup file.
# Reads DB_NAME and DB_USER from DATABASE_URL in /etc/zerodha-mcp/.env
#
# Without an argument, lists available backups and exits.
# With an argument, drops and recreates the database, then restores.
#
# Run as: sudo bash infra/06_restore.sh [/path/to/backup.sql.gz]
set -euo pipefail

ENV_FILE="/etc/zerodha-mcp/.env"
BACKUP_DIR="/var/backups/postgresql"
BACKUP_FILE="${1:-}"

# Parse DB_NAME and DB_USER from DATABASE_URL
_URL=""
if [ -f "${ENV_FILE}" ]; then
  _URL=$(grep '^DATABASE_URL=' "${ENV_FILE}" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
fi
if [ -z "${_URL}" ]; then
  echo "ERROR: DATABASE_URL not found in ${ENV_FILE}" >&2
  exit 1
fi
_URL=$(echo "${_URL}" | sed 's|postgresql+asyncpg://|postgresql://|')
DB_USER=$(echo "${_URL}" | sed 's|postgresql://\([^:]*\):.*|\1|')
DB_NAME=$(echo "${_URL}" | sed 's|.*/\([^?]*\).*|\1|')

list_backups() {
  echo "Available backups in ${BACKUP_DIR}:"
  echo ""
  ls -lht "${BACKUP_DIR}/${DB_NAME}_"*.sql.gz 2>/dev/null \
    || echo "  No backups found."
  echo ""
}

if [ -z "${BACKUP_FILE}" ]; then
  list_backups
  echo "Usage: sudo bash infra/06_restore.sh <backup_file.sql.gz>"
  exit 0
fi

if [ ! -f "${BACKUP_FILE}" ]; then
  echo "ERROR: File not found: ${BACKUP_FILE}"
  echo ""
  list_backups
  exit 1
fi

SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
echo "============================================================"
echo " RESTORE ${DB_NAME}"
echo "============================================================"
echo " Backup file : ${BACKUP_FILE}"
echo " File size   : ${SIZE}"
echo " Target DB   : ${DB_NAME}"
echo " Owner       : ${DB_USER}"
echo "============================================================"
echo ""
echo "WARNING: This will DROP the existing '${DB_NAME}' database"
echo "and restore it from the backup above. All current data will"
echo "be permanently deleted."
echo ""
read -rp "Type 'yes' to continue: " CONFIRM

if [ "${CONFIRM}" != "yes" ]; then
  echo "Aborted. No changes made."
  exit 0
fi

echo ""
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Terminating active connections to ${DB_NAME}..."
sudo -u postgres psql -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB_NAME}' AND pid <> pg_backend_pid();"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Dropping database ${DB_NAME}..."
sudo -u postgres psql -c "DROP DATABASE IF EXISTS ${DB_NAME};"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Recreating database ${DB_NAME}..."
sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restoring from backup..."
gunzip -c "${BACKUP_FILE}" | sudo -u postgres psql "${DB_NAME}"

echo ""
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restore complete."
sudo -u postgres psql -c "\l" | grep "${DB_NAME}"
