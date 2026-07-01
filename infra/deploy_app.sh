#!/usr/bin/env bash
# Production deployment script — Zerodha MCP on Oracle VM.
#
# Deployment flow:
#   1. git pull (latest code)
#   2. uv sync (install/update dependencies)
#   3. alembic upgrade head (migrate DB — blocks if migration fails)
#   4. systemctl restart zerodha-mcp (restart app only after migration succeeds)
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
# Step 4: Restart application
# ---------------------------------------------------------------------------
echo ""
echo "[4/4] Restarting zerodha-mcp service..."

if "${SETUP_MODE}"; then
  echo "  Installing systemd service (first-time setup)..."
  sudo mkdir -p /var/lib/zerodha-mcp
  sudo chown ubuntu:ubuntu /var/lib/zerodha-mcp
  sudo cp "${REPO_ROOT}/infra/systemd/zerodha-mcp.service" \
    /etc/systemd/system/zerodha-mcp.service
  sudo systemctl daemon-reload
  sudo systemctl enable zerodha-mcp
fi

sudo systemctl restart zerodha-mcp
sleep 3

if sudo systemctl is-active --quiet zerodha-mcp; then
  echo "  Service is running."
else
  echo "  ERROR: Service failed to start. Check logs:"
  echo "    sudo journalctl -u zerodha-mcp -n 50"
  exit 1
fi

echo ""
echo "============================================================"
echo " Deploy complete."
echo " Commit  : $(git log --oneline -1)"
echo " Schema  : $(uv run alembic current)"
echo " Service : $(sudo systemctl is-active zerodha-mcp)"
echo ""
echo " Live logs: sudo journalctl -u zerodha-mcp -f"
echo "============================================================"
