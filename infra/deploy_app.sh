#!/usr/bin/env bash
# Production deployment script — Zerodha MCP on Oracle VM.
#
# Deployment flow:
#   1. git pull (latest code)
#   2. uv sync (install/update dependencies)
#   3. alembic upgrade head (migrate DB — blocks if migration fails)
#   4. systemctl restart zerodha-mcp AND zerodha-monitor (restart both only
#      after migration succeeds)
#
# zerodha-monitor is a separate long-running process (src/monitor/service.py)
# that reads the same DB schema and alert logic as zerodha-mcp — restarting
# only zerodha-mcp left the monitor running stale alert code against a
# migrated schema (see src/telegram_admin/service_manager.py, which already
# restarts both for the same reason on manual /restart).
#
# telegram-admin is a third long-running process (src/telegram_admin/main.py,
# a python-telegram-bot long-poll loop) that imports src/telegram_admin/*
# directly — it was missing from this list, so bot command changes (/buy,
# /sell, /search, etc.) silently kept running on stale code until someone
# restarted it by hand (2026-07-11).
#
# Usage:
#   bash infra/deploy_app.sh              # standard deploy from current branch
#   bash infra/deploy_app.sh --no-pull    # skip git pull (deploy current working tree)
#   bash infra/deploy_app.sh --setup      # first-time: install systemd service too
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="/etc/zerodha-mcp/.env"
SKIP_PULL=false
SETUP_MODE=false
RESTART_SERVICES=("zerodha-mcp" "zerodha-monitor" "telegram-admin")

for arg in "$@"; do
  case "${arg}" in
    --no-pull) SKIP_PULL=true ;;
    --setup)   SETUP_MODE=true ;;
  esac
done

cd "${REPO_ROOT}"

echo "============================================================"
echo " Zerodha MCP — Production Deploy"
echo " Repo   : ${REPO_ROOT}"
echo " Env    : ${ENV_FILE}"
echo " $(date '+%Y-%m-%d %H:%M:%S IST')"
echo "============================================================"

# Verify the environment file exists before doing anything
if [ ! -f "${ENV_FILE}" ]; then
  echo ""
  echo "ERROR: ${ENV_FILE} not found."
  echo "Run first: sudo bash infra/env/setup_env.sh"
  exit 1
fi

# Load environment for this script (DATABASE_URL needed for migration)
set -a; source "${ENV_FILE}"; set +a

# ---------------------------------------------------------------------------
# Step 1: Git pull
# ---------------------------------------------------------------------------
if ! "${SKIP_PULL}"; then
  echo ""
  echo "[1/4] Pulling latest code..."
  git fetch origin
  BRANCH=$(git rev-parse --abbrev-ref HEAD)
  git pull origin "${BRANCH}"
  echo "  Branch: ${BRANCH}"
  echo "  Commit: $(git log --oneline -1)"
else
  echo "[1/4] Skipping git pull (--no-pull)"
  echo "  Commit: $(git log --oneline -1)"
fi

# ---------------------------------------------------------------------------
# Step 2: uv sync (install / update dependencies)
# ---------------------------------------------------------------------------
echo ""
echo "[2/4] Syncing dependencies..."
uv sync --frozen
echo "  Dependencies up to date."

# ---------------------------------------------------------------------------
# Step 3: Alembic migration — runs BEFORE app restart
# Application NEVER starts with a stale schema.
# ---------------------------------------------------------------------------
echo ""
echo "[3/4] Running database migrations..."
DB_URL_SAFE=$(echo "${DATABASE_URL:-}" | sed 's|:\([^:@]*\)@|:***@|')
echo "  DATABASE_URL: ${DB_URL_SAFE}"

# Capture alembic output — if it fails, the entire script fails (set -e)
# and the application is NOT restarted, leaving the old version running.
uv run alembic upgrade head
echo "  Migration complete: $(uv run alembic current)"

# ---------------------------------------------------------------------------
# Step 4: Restart application services
# ---------------------------------------------------------------------------
echo ""
echo "[4/4] Restarting services: ${RESTART_SERVICES[*]}..."

if "${SETUP_MODE}"; then
  echo "  Installing systemd services (first-time setup)..."
  sudo mkdir -p /var/lib/zerodha-mcp
  sudo chown ubuntu:ubuntu /var/lib/zerodha-mcp
  for service in "${RESTART_SERVICES[@]}"; do
    sudo cp "${REPO_ROOT}/infra/systemd/${service}.service" \
      "/etc/systemd/system/${service}.service"
  done
  sudo systemctl daemon-reload
  for service in "${RESTART_SERVICES[@]}"; do
    sudo systemctl enable "${service}"
  done
fi

# Restart every service before checking any of them — a failure in one
# must not silently leave another running the old code with a new schema.
for service in "${RESTART_SERVICES[@]}"; do
  sudo systemctl restart "${service}"
done
sleep 3

DEPLOY_FAILED=false
for service in "${RESTART_SERVICES[@]}"; do
  if sudo systemctl is-active --quiet "${service}"; then
    echo "  ${service} is running."
  else
    echo "  ERROR: ${service} failed to start. Check logs:"
    echo "    sudo journalctl -u ${service} -n 50"
    DEPLOY_FAILED=true
  fi
done

if "${DEPLOY_FAILED}"; then
  exit 1
fi

echo ""
echo "============================================================"
echo " Deploy complete."
echo " Commit  : $(git log --oneline -1)"
echo " Schema  : $(uv run alembic current)"
for service in "${RESTART_SERVICES[@]}"; do
  echo " Service : ${service} — $(sudo systemctl is-active "${service}")"
done
echo ""
echo " Live logs: sudo journalctl -u zerodha-mcp -f"
echo "           sudo journalctl -u zerodha-monitor -f"
echo "============================================================"
