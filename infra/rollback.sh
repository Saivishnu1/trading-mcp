#!/usr/bin/env bash
# Emergency rollback — reverts both the database migration and the git commit.
#
# Usage:
#   bash infra/rollback.sh                  # rolls back 1 migration step + git HEAD~1
#   bash infra/rollback.sh --db-only        # rolls back 1 migration step, keeps git state
#   bash infra/rollback.sh --db-only <rev>  # rolls back to a specific alembic revision
#
# This script stops the application before rolling back and restarts it after.
# It does NOT restore data — only schema. Use pg_dump backups for data recovery.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="/etc/zerodha-mcp/.env"
MODE="${1:-}"
TARGET="${2:--1}"  # default: roll back one step

cd "${REPO_ROOT}"

# Load environment
if [ -f "${ENV_FILE}" ]; then
  set -a; source "${ENV_FILE}"; set +a
elif [ -f ".env" ]; then
  set -a; source ".env"; set +a
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL is not set."
  exit 1
fi

echo "============================================================"
echo " ROLLBACK — Zerodha MCP"
echo " Mode   : ${MODE:-full (DB + git)}"
echo " DB rev : ${TARGET}"
echo "============================================================"
echo ""

# Show what we're rolling back FROM
echo "Current state:"
echo "  Git:      $(git log --oneline -1)"
echo "  Alembic:  $(uv run alembic current 2>/dev/null || echo 'unknown')"
echo ""

read -rp "Proceed with rollback? (yes/no): " CONFIRM
if [ "${CONFIRM}" != "yes" ]; then
  echo "Aborted."
  exit 0
fi

# Step 1: Stop the application
echo ""
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Stopping zerodha-mcp service..."
if systemctl is-active --quiet zerodha-mcp 2>/dev/null; then
  sudo systemctl stop zerodha-mcp
  echo "Service stopped."
else
  echo "Service was not running."
fi

# Step 2: Rollback database schema
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Rolling back database to: ${TARGET}"
uv run alembic downgrade "${TARGET}"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Database schema rolled back."
uv run alembic current

# Step 3: Rollback git (unless --db-only)
if [ "${MODE}" != "--db-only" ]; then
  echo ""
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Rolling back git to HEAD~1..."
  echo "Current commit: $(git log --oneline -1)"
  git reset --hard HEAD~1
  echo "After rollback: $(git log --oneline -1)"
  uv sync --frozen
fi

# Step 4: Restart the application
echo ""
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restarting zerodha-mcp service..."
if systemctl list-unit-files zerodha-mcp.service &>/dev/null; then
  sudo systemctl start zerodha-mcp
  sleep 3
  sudo systemctl status zerodha-mcp --no-pager
else
  echo "systemd service not installed — start the app manually."
fi

echo ""
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Rollback complete."
