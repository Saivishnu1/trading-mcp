#!/usr/bin/env bash
# Step 1 of 3 — Export data from Turso to JSON files.
#
# Uses the Turso HTTP API directly (no CLI dependency) — more reliable than
# parsing turso db shell output which is designed for interactive terminals.
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

mkdir -p "${EXPORT_DIR}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "==> Exporting from Turso: ${TURSO_DATABASE_URL}"
echo "    Output: ${EXPORT_DIR}/"
echo ""

# ---------------------------------------------------------------------------
# Export via Turso HTTP API — returns clean JSON, no CLI formatting
# ---------------------------------------------------------------------------
python3 - <<PYEOF
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

db_url   = os.environ["TURSO_DATABASE_URL"].rstrip("/")
token    = os.environ["TURSO_AUTH_TOKEN"]
http_url = db_url.replace("libsql://", "https://") + "/v2/pipeline"
export_dir = "${EXPORT_DIR}"

def turso_query(sql: str) -> list[dict]:
    """Execute SQL against Turso HTTP API and return list of row dicts."""
    payload = json.dumps({
        "requests": [
            {"type": "execute", "stmt": {"sql": sql}},
            {"type": "close"}
        ]
    }).encode()

    req = urllib.request.Request(
        http_url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"ERROR: HTTP {e.code} from Turso API", file=sys.stderr)
        print(e.read().decode(), file=sys.stderr)
        sys.exit(1)

    result = body["results"][0]
    if result["type"] == "error":
        print(f"ERROR from Turso: {result['error']}", file=sys.stderr)
        sys.exit(1)

    cols = [c["name"] for c in result["response"]["result"]["cols"]]
    rows = []
    for raw_row in result["response"]["result"]["rows"]:
        row = {}
        for col, cell in zip(cols, raw_row):
            if isinstance(cell, dict):
                # Turso cell: {"type": "text"|"integer"|"float"|"blob"|"null", "value": ...}
                # "null" type has no "value" key
                row[col] = cell.get("value")  # None for null cells
            else:
                row[col] = cell
        rows.append(row)
    return rows


# Export trades
print("==> Exporting trades...")
trades = turso_query("SELECT * FROM trades")
with open(f"{export_dir}/trades.json", "w") as f:
    json.dump(trades, f, indent=2, default=str)
print(f"  trades: {len(trades)} rows")

# Export recommendation_log
print("==> Exporting recommendation_log...")
recs = turso_query("SELECT * FROM recommendation_log")
with open(f"{export_dir}/recommendation_log.json", "w") as f:
    json.dump(recs, f, indent=2, default=str)
print(f"  recommendation_log: {len(recs)} rows")

# Write export metadata
print("")
print("==> Writing export metadata...")
meta = {
    "exported_at": datetime.now(timezone.utc).isoformat(),
    "export_timestamp": "${TIMESTAMP}",
    "source": "${TURSO_DATABASE_URL}",
    "tables": {
        "trades": len(trades),
        "recommendation_log": len(recs),
    },
    "excluded_tables": ["sessions", "api_keys"],
    "excluded_reason": "ephemeral — regenerate on first login",
}
with open(f"{export_dir}/export_meta.json", "w") as f:
    json.dump(meta, f, indent=2)
print(json.dumps(meta, indent=2))
PYEOF

echo ""
echo "Export complete: ${EXPORT_DIR}/"
ls -lh "${EXPORT_DIR}/"
echo ""
echo "Next step: bash infra/turso_migration/02_stage_to_postgres.sh"
