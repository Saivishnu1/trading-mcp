#!/usr/bin/env bash
# Restores zerodha_mcp from a pg_dump backup file.
# Run as: sudo bash 06_restore.sh [/path/to/backup.sql.gz]
#
# Without an argument, lists available backups and exits.
# With an argument, drops and recreates the database, then restores.
set -euo pipefail

BACKUP_DIR="/var/backups/postgresql"
DB_NAME="zerodha_mcp"
DB_USER="zerodha_app"
BACKUP_FILE="${1:-}"

list_backups() {
  echo "Available backups in ${BACKUP_DIR}:"
  echo ""
  ls -lht "${BACKUP_DIR}/${DB_NAME}_"*.sql.gz 2>/dev/null \
    || echo "  No backups found."
  echo ""
}

if [ -z "${BACKUP_FILE}" ]; then
  list_backups
  echo "Usage: sudo bash 06_restore.sh <backup_file.sql.gz>"
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
echo " RESTORE zerodha_mcp"
echo "============================================================"
echo " Backup file : ${BACKUP_FILE}"
echo " File size   : ${SIZE}"
echo " Target DB   : ${DB_NAME}"
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
