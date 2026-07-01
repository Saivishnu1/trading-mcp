#!/usr/bin/env bash
# Run Alembic migrations safely with double-layer locking.
#
# Locking strategy:
#   Layer 1 — flock /var/lock/zerodha-mcp-migrate.lock (OS-level, this script)
#              Blocks a second invocation of THIS script before it even connects.
#   Layer 2 — pg_advisory_lock(987654321) (DB-level, migrations/env.py)
#              Blocks any process that reaches PostgreSQL concurrently,
#              including scripts that call alembic directly.
#
# Usage:
#   bash infra/migrate.sh             # upgrade to head
#   bash infra/migrate.sh --dry-run   # print SQL without executing (no lock)
#   bash infra/migrate.sh --current   # show current revision (no lock)
#   bash infra/migrate.sh --history   # show full migration history (no lock)
#   bash infra/migrate.sh --downgrade <rev>  # downgrade to revision (locked)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="/etc/zerodha-mcp/.env"
LOCK_FILE="/var/lock/zerodha-mcp-migrate.lock"
MODE="${1:-}"

cd "${REPO_ROOT}"

# Load environment — DATABASE_URL must be set
if [ -f "${ENV_FILE}" ]; then
  set -a; source "${ENV_FILE}"; set +a
elif [ -f ".env" ]; then
  set -a; source ".env"; set +a
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL is not set."
  echo "Set it in ${ENV_FILE} or .env"
  exit 1
fi

# Mask the password in log output
DB_URL_SAFE=$(echo "${DATABASE_URL}" | sed 's|:\([^:@]*\)@|:***@|')
echo "[$(date '+%Y-%m-%d %H:%M:%S')] DATABASE_URL: ${DB_URL_SAFE}"

# Read-only commands — no lock needed, no DDL risk
case "${MODE}" in
  --dry-run)
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Generating SQL diff (dry run — no lock, no DDL)..."
    uv run alembic upgrade head --sql
    exit 0
    ;;
  --current)
    uv run alembic current
    exit 0
    ;;
  --history)
    uv run alembic history --verbose
    exit 0
    ;;
esac

# DDL commands — acquire OS-level flock before proceeding.
# flock --exclusive --timeout 60 waits up to 60 s, then fails rather than
# running a migration inside an already-migrating deploy.
run_locked() {
  flock --exclusive --timeout 60 "${LOCK_FILE}" bash -c "$1"
}

case "${MODE}" in
  --downgrade)
    TARGET="${2:-}"
    if [ -z "${TARGET}" ]; then
      echo "ERROR: --downgrade requires a revision target."
      echo "Usage: bash infra/migrate.sh --downgrade <revision>"
      echo "       bash infra/migrate.sh --downgrade -1"
      exit 1
    fi
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Acquiring migration lock..."
    run_locked "
      echo '[$(date \"+%Y-%m-%d %H:%M:%S\")] Downgrading to: ${TARGET}'
      uv run alembic downgrade '${TARGET}'
      echo '[$(date \"+%Y-%m-%d %H:%M:%S\")] Downgrade complete.'
      uv run alembic current
    "
    ;;
  "")
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Acquiring migration lock..."
    run_locked "
      echo '[$(date \"+%Y-%m-%d %H:%M:%S\")] Running: alembic upgrade head'
      uv run alembic upgrade head
      echo '[$(date \"+%Y-%m-%d %H:%M:%S\")] Migration complete.'
      uv run alembic current
    "
    ;;
  *)
    echo "Unknown option: ${MODE}"
    echo "Usage: bash infra/migrate.sh [--dry-run|--current|--history|--downgrade <rev>]"
    exit 1
    ;;
esac
