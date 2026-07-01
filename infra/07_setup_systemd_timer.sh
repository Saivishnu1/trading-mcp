#!/usr/bin/env bash
# Installs the backup script and systemd service + timer for daily PostgreSQL backups.
# Run as: sudo bash 07_setup_systemd_timer.sh
#
# Assumes this script is run from the infra/ directory, i.e.:
#   cd /home/ubuntu/zerodha-mcp/infra && sudo bash 07_setup_systemd_timer.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DEST="/home/ubuntu/scripts"

echo "==> [1/4] Installing backup script to ${SCRIPTS_DEST}..."
mkdir -p "${SCRIPTS_DEST}"
cp "${SCRIPT_DIR}/05_backup.sh" "${SCRIPTS_DEST}/backup_postgres.sh"
chmod +x "${SCRIPTS_DEST}/backup_postgres.sh"

echo "==> [2/4] Installing systemd units..."
cp "${SCRIPT_DIR}/systemd/backup_postgres.service" /etc/systemd/system/backup_postgres.service
cp "${SCRIPT_DIR}/systemd/backup_postgres.timer"   /etc/systemd/system/backup_postgres.timer

echo "==> [3/4] Reloading systemd and enabling timer..."
systemctl daemon-reload
systemctl enable backup_postgres.timer
systemctl start backup_postgres.timer

echo "==> [4/4] Running a test backup now via systemd..."
systemctl start backup_postgres.service

echo ""
echo "=== Timer status ==="
systemctl list-timers backup_postgres.timer --no-pager

echo ""
echo "=== Last backup service output ==="
journalctl -u backup_postgres.service -n 30 --no-pager

echo ""
echo "Backup timer is active. Next run: 02:00 IST daily."
echo "Monitor with: sudo journalctl -u backup_postgres.service -f"
