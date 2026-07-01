#!/usr/bin/env bash
# Master runner — runs all infra steps in order on the Oracle VM.
# Run as: sudo bash deploy.sh
#
# Usage:
#   sudo bash deploy.sh                    # full setup
#   sudo bash deploy.sh --skip-install     # skip apt install (already done)
#   sudo bash deploy.sh --healthcheck      # run health check only
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKIP_INSTALL=false
HEALTHCHECK_ONLY=false

for arg in "$@"; do
  case "${arg}" in
    --skip-install)    SKIP_INSTALL=true ;;
    --healthcheck)     HEALTHCHECK_ONLY=true ;;
  esac
done

if "${HEALTHCHECK_ONLY}"; then
  bash "${SCRIPT_DIR}/08_healthcheck.sh"
  exit $?
fi

# ---------------------------------------------------------------------------
# Prompt for the database password before doing anything else
# ---------------------------------------------------------------------------
echo "============================================================"
echo " Zerodha MCP — PostgreSQL 17 Production Setup"
echo " Oracle VM.Standard.A1.Flex (ARM64, 24 GB)"
echo "============================================================"
echo ""
echo "You will be prompted once for the PostgreSQL application user"
echo "password (zerodha_app). Store this in a password manager."
echo ""
read -rsp "Enter DB password for zerodha_app: " DB_PASSWORD
echo ""
read -rsp "Confirm DB password: " DB_PASSWORD_CONFIRM
echo ""

if [ "${DB_PASSWORD}" != "${DB_PASSWORD_CONFIRM}" ]; then
  echo "ERROR: Passwords do not match. Aborting."
  exit 1
fi

if [ ${#DB_PASSWORD} -lt 16 ]; then
  echo "ERROR: Password must be at least 16 characters. Aborting."
  exit 1
fi

echo ""
echo "Password accepted. Starting setup..."
echo ""

# ---------------------------------------------------------------------------
# Step 1: Install PostgreSQL 17
# ---------------------------------------------------------------------------
if ! "${SKIP_INSTALL}"; then
  echo "============================================================"
  echo " STEP 1/6: Install PostgreSQL 17"
  echo "============================================================"
  bash "${SCRIPT_DIR}/01_install_postgres.sh"
else
  echo "[SKIP] Step 1: PostgreSQL install skipped (--skip-install)"
fi

# ---------------------------------------------------------------------------
# Step 2: Configure postgresql.conf and pg_hba.conf
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo " STEP 2/6: Configure PostgreSQL"
echo "============================================================"
bash "${SCRIPT_DIR}/02_configure_postgres.sh"

# ---------------------------------------------------------------------------
# Step 3: Create database, user, schemas, extensions
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo " STEP 3/6: Create database, schemas, extensions"
echo "============================================================"
sudo -u postgres psql -v db_password="${DB_PASSWORD}" -f "${SCRIPT_DIR}/03_create_db.sql"
unset DB_PASSWORD
unset DB_PASSWORD_CONFIRM

# ---------------------------------------------------------------------------
# Step 4: Firewall
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo " STEP 4/6: Configure ufw firewall"
echo "============================================================"
bash "${SCRIPT_DIR}/04_firewall.sh"

# ---------------------------------------------------------------------------
# Step 5: Systemd backup timer
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo " STEP 5/6: Install backup script and systemd timer"
echo "============================================================"
bash "${SCRIPT_DIR}/07_setup_systemd_timer.sh"

# ---------------------------------------------------------------------------
# Step 6: Health check
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo " STEP 6/6: Health check"
echo "============================================================"
bash "${SCRIPT_DIR}/08_healthcheck.sh"

echo ""
echo "============================================================"
echo " Setup complete."
echo ""
echo " PostgreSQL 17 is running at: localhost:5432"
echo " Database    : zerodha_mcp"
echo " App user    : zerodha_app"
echo " Schemas     : zerodha (default), migration, public"
echo " Backups     : /var/backups/postgresql/ — daily at 02:00 IST"
echo " Data files  : /var/lib/postgresql/17/main/"
echo ""
echo " Connection string (for .env on this VM):"
echo "   DATABASE_URL=postgresql+asyncpg://zerodha_app:PASSWORD@127.0.0.1:5432/zerodha_mcp"
echo ""
echo " Remember to:"
echo "   1. Add port 22/80/443 to your OCI Security List (not 5432)"
echo "   2. Store the DB password in your password manager"
echo "   3. Never commit the password to git"
echo "============================================================"
