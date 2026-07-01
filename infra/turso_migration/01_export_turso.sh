#!/usr/bin/env bash
# Step 1 of 3 — Export data from Turso to local SQLite files.
#
# Requires the Turso CLI: https://docs.turso.tech/cli/installation
#   curl -sSfL https://get.tur.so/install.sh | bash
#   turso auth login
#
# Usage:
#   bash infra/turso_migration/01_export_turso.sh
#
# Output files (written to infra/turso_migration/export/):
#   trades.json              — all rows from the trades table
#   recommendation_log.json  — all rows from recommendation_log
#   export_meta.json         — row counts, export timestamp, schema version
#
# Sessions and api_keys are intentionally NOT exported —
# they are ephemeral and regenerate on first login to the Oracle VM.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPORT_DIR="${SCRIPT_DIR}/export"
ENV_FILE="/etc/zerodha-mcp/.env"

# Load TURSO_DATABASE_URL and TURSO_AUTH_TOKEN
if [ -f "${ENV_FILE}" ]; then
  set -a; source "${ENV_FILE}"; set +a
elif [ -f ".env" ]; then
  set -a; source ".env"; set +a
fi

if [ -z "${TURSO_DATABASE_URL:-}" ] || [ -z "${TURSO_AUTH_TOKEN:-}" ]; then
  echo "ERROR: TURSO_DATABASE_URL and TURSO_AUTH_TOKEN must be set."
  echo "Check /etc/zerodha-mcp/.env or .env"
  exit 1
fi

if ! command -v turso &>/dev/null; then
  echo "ERROR: turso CLI not found."
  echo "Install: curl -sSfL https://get.tur.so/install.sh | bash"
  exit 1
fi

mkdir -p "${EXPORT_DIR}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "==> Exporting from Turso: ${TURSO_DATABASE_URL}"
echo "    Output: ${EXPORT_DIR}/"
echo ""

# ---------------------------------------------------------------------------
# Helper: run a SQL query against Turso and save JSON output
# ---------------------------------------------------------------------------
turso_query() {
  local query="$1"
  # turso db shell outputs tab-separated rows; we use Python to convert to JSON
  turso db shell "${TURSO_DATABASE_URL}" \
    --auth-token "${TURSO_AUTH_TOKEN}" \
    "${query}" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Export trades
# ---------------------------------------------------------------------------
echo "==> Exporting trades..."
turso_query "SELECT * FROM trades;" > "${EXPORT_DIR}/trades_raw.tsv"

python3 - <<PYEOF
import csv, json, sys

with open("${EXPORT_DIR}/trades_raw.tsv") as f:
    reader = csv.DictReader(f, delimiter='\t')
    rows = list(reader)

with open("${EXPORT_DIR}/trades.json", "w") as f:
    json.dump(rows, f, indent=2, default=str)

print(f"  trades: {len(rows)} rows")
PYEOF

# ---------------------------------------------------------------------------
# Export recommendation_log
# ---------------------------------------------------------------------------
echo "==> Exporting recommendation_log..."
turso_query "SELECT * FROM recommendation_log;" > "${EXPORT_DIR}/recommendation_log_raw.tsv"

python3 - <<PYEOF
import csv, json, sys

with open("${EXPORT_DIR}/recommendation_log_raw.tsv") as f:
    reader = csv.DictReader(f, delimiter='\t')
    rows = list(reader)

with open("${EXPORT_DIR}/recommendation_log.json", "w") as f:
    json.dump(rows, f, indent=2, default=str)

print(f"  recommendation_log: {len(rows)} rows")
PYEOF

# ---------------------------------------------------------------------------
# Export metadata
# ---------------------------------------------------------------------------
echo "==> Writing export metadata..."
TRADES_COUNT=$(python3 -c "import json; print(len(json.load(open('${EXPORT_DIR}/trades.json'))))")
REC_COUNT=$(python3 -c "import json; print(len(json.load(open('${EXPORT_DIR}/recommendation_log.json'))))")

python3 - <<PYEOF
import json
from datetime import datetime, timezone

meta = {
    "exported_at": datetime.now(timezone.utc).isoformat(),
    "export_timestamp": "${TIMESTAMP}",
    "source": "${TURSO_DATABASE_URL}",
    "tables": {
        "trades": ${TRADES_COUNT},
        "recommendation_log": ${REC_COUNT},
    },
    "excluded_tables": ["sessions", "api_keys"],
    "excluded_reason": "ephemeral — regenerate on first login",
}

with open("${EXPORT_DIR}/export_meta.json", "w") as f:
    json.dump(meta, f, indent=2)

print(json.dumps(meta, indent=2))
PYEOF

# Clean up raw TSV files (JSON is the canonical export format)
rm -f "${EXPORT_DIR}/trades_raw.tsv" "${EXPORT_DIR}/recommendation_log_raw.tsv"

echo ""
echo "Export complete: ${EXPORT_DIR}/"
ls -lh "${EXPORT_DIR}/"
echo ""
echo "Next step: bash infra/turso_migration/02_stage_to_postgres.sh"
