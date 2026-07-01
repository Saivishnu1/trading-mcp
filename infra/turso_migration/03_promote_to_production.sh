#!/usr/bin/env bash
# Step 3 of 3 — Promote staging data into live production tables.
#
# Copies migration.trades → zerodha.trades
#       migration.recommendation_log → journal.recommendation_log
#
# Operation order:
#   1. Compute and save pre-promotion checksums (migration_validation.json)
#   2. Show staging vs. export counts; warn on mismatch
#   3. Confirm with user before touching production
#   4. INSERT ... SELECT with ON CONFLICT DO NOTHING (safe to re-run)
#   5. Compute post-promotion checksums and verify they match staging
#   6. Write final migration_validation.json with full audit trail
#   7. Rename staging tables to trades_YYYYMMDD / recommendation_log_YYYYMMDD
#      (never delete — retained as an immutable archive)
#
# Usage:
#   bash infra/turso_migration/03_promote_to_production.sh
#   bash infra/turso_migration/03_promote_to_production.sh --dry-run
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="/etc/zerodha-mcp/.env"
DRY_RUN=false
[ "${1:-}" = "--dry-run" ] && DRY_RUN=true

if [ -f "${ENV_FILE}" ]; then
  set -a; source "${ENV_FILE}"; set +a
elif [ -f ".env" ]; then
  set -a; source ".env"; set +a
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL is not set."
  exit 1
fi

DATESTAMP=$(date +%Y%m%d)

uv run python3 - <<PYEOF
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

db_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
dry_run = "${DRY_RUN}" == "true"
datestamp = "${DATESTAMP}"
script_dir = Path("${SCRIPT_DIR}")
export_dir = script_dir / "export"

import psycopg2

conn = psycopg2.connect(db_url)
conn.autocommit = False
cur = conn.cursor()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def count(table: str) -> int:
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]

def checksum(table: str) -> str:
    """MD5 over all IDs sorted deterministically.

    This is a row-existence checksum — it answers "are all source rows present
    in the destination?" without comparing column values, which may differ for
    nullable fields with SQLite/PostgreSQL default differences.
    """
    cur.execute(f"""
        SELECT md5(string_agg(id::text, ',' ORDER BY id))
        FROM {table}
    """)
    result = cur.fetchone()[0]
    return result or ""

# ---------------------------------------------------------------------------
# Pre-promotion: staging counts and checksums
# ---------------------------------------------------------------------------
staged_trades    = count("migration.trades")
staged_recs      = count("migration.recommendation_log")
prod_trades_pre  = count("zerodha.trades")
prod_recs_pre    = count("journal.recommendation_log")

staging_checksum_trades = checksum("migration.trades")
staging_checksum_recs   = checksum("migration.recommendation_log")

meta_path = export_dir / "export_meta.json"
if meta_path.exists():
    with open(meta_path) as f:
        meta = json.load(f)
    expected_trades = meta["tables"]["trades"]
    expected_recs   = meta["tables"]["recommendation_log"]
    export_timestamp = meta.get("exported_at", "unknown")
else:
    expected_trades  = staged_trades
    expected_recs    = staged_recs
    export_timestamp = "unknown"

print("============================================================")
print(f" {'DRY RUN — ' if dry_run else ''}Promote staging → production")
print("============================================================")
print(f"  Turso export time            : {export_timestamp}")
print(f"  migration.trades             : {staged_trades} staged  (exported {expected_trades})")
print(f"  migration.recommendation_log : {staged_recs} staged  (exported {expected_recs})")
print(f"  zerodha.trades               : {prod_trades_pre} existing")
print(f"  journal.recommendation_log   : {prod_recs_pre} existing")
print("")
print(f"  Staging checksum (trades)    : {staging_checksum_trades}")
print(f"  Staging checksum (recs)      : {staging_checksum_recs}")
print("")

count_ok = True
if staged_trades != expected_trades:
    print(f"  WARNING: staged trades ({staged_trades}) != exported ({expected_trades})")
    count_ok = False
if staged_recs != expected_recs:
    print(f"  WARNING: staged recs ({staged_recs}) != exported ({expected_recs})")
    count_ok = False
if count_ok:
    print("  Count check: PASS")

if dry_run:
    print("")
    print("DRY RUN — no changes made.")
    conn.close()
    sys.exit(0)

print("")
# stdin is the heredoc body — read user input directly from the terminal
sys.stdout.write("Type 'promote' to continue: ")
sys.stdout.flush()
with open("/dev/tty") as tty:
    confirm = tty.readline().strip()
if confirm != "promote":
    print("Aborted.")
    conn.close()
    sys.exit(0)

migration_start = datetime.now(timezone.utc)

# ---------------------------------------------------------------------------
# Promote trades: migration.trades → zerodha.trades
# ---------------------------------------------------------------------------
print("")
print("==> Promoting trades...")
cur.execute("""
    INSERT INTO zerodha.trades
    SELECT * FROM migration.trades
    ON CONFLICT (id) DO NOTHING
""")
trades_inserted = cur.rowcount
conn.commit()
print(f"  Inserted: {trades_inserted} new rows")

# ---------------------------------------------------------------------------
# Promote recommendation_log: migration.recommendation_log → journal.recommendation_log
# ---------------------------------------------------------------------------
print("==> Promoting recommendation_log...")
cur.execute("""
    INSERT INTO journal.recommendation_log
    SELECT * FROM migration.recommendation_log
    ON CONFLICT (id) DO NOTHING
""")
recs_inserted = cur.rowcount
conn.commit()
print(f"  Inserted: {recs_inserted} new rows")

migration_end = datetime.now(timezone.utc)

# ---------------------------------------------------------------------------
# Post-promotion: counts and checksums on destination tables
# ---------------------------------------------------------------------------
prod_trades_post = count("zerodha.trades")
prod_recs_post   = count("journal.recommendation_log")

dest_checksum_trades = checksum("zerodha.trades")
dest_checksum_recs   = checksum("journal.recommendation_log")

# The destination checksum will include pre-existing rows if any were present.
# For a first-deploy the checksums must match staging exactly.
# For a re-run into a non-empty table they will differ — both are recorded.
trades_checksum_match = (staging_checksum_trades == dest_checksum_trades) if prod_trades_pre == 0 else None
recs_checksum_match   = (staging_checksum_recs == dest_checksum_recs)     if prod_recs_pre == 0 else None

print("")
print("=== Post-promotion validation ===")
print(f"  zerodha.trades              : {prod_trades_pre} → {prod_trades_post} (+{prod_trades_post - prod_trades_pre})")
print(f"  journal.recommendation_log  : {prod_recs_pre} → {prod_recs_post} (+{prod_recs_post - prod_recs_pre})")
print(f"  Dest checksum (trades)      : {dest_checksum_trades}")
print(f"  Dest checksum (recs)        : {dest_checksum_recs}")

if trades_checksum_match is not None:
    status = "PASS" if trades_checksum_match else "FAIL — checksums differ"
    print(f"  Checksum match (trades)     : {status}")
if recs_checksum_match is not None:
    status = "PASS" if recs_checksum_match else "FAIL — checksums differ"
    print(f"  Checksum match (recs)       : {status}")

# ---------------------------------------------------------------------------
# Write migration_validation.json — permanent audit trail
# ---------------------------------------------------------------------------
validation = {
    "migration_time": migration_end.isoformat(),
    "migration_duration_seconds": round((migration_end - migration_start).total_seconds(), 2),
    "export_timestamp": export_timestamp,
    "trades": {
        "source_count":    staged_trades,
        "exported_count":  expected_trades,
        "dest_count":      prod_trades_post,
        "inserted":        trades_inserted,
        "source_checksum": staging_checksum_trades,
        "dest_checksum":   dest_checksum_trades,
        "checksum_match":  trades_checksum_match,
    },
    "recommendation_log": {
        "source_count":    staged_recs,
        "exported_count":  expected_recs,
        "dest_count":      prod_recs_post,
        "inserted":        recs_inserted,
        "source_checksum": staging_checksum_recs,
        "dest_checksum":   dest_checksum_recs,
        "checksum_match":  recs_checksum_match,
    },
    "excluded_tables": ["sessions", "api_keys"],
    "excluded_reason": "ephemeral — regenerate on first login",
}

validation_path = script_dir / "export" / "migration_validation.json"
with open(validation_path, "w") as f:
    json.dump(validation, f, indent=2)

print("")
print(f"  Audit trail written: {validation_path}")
print(json.dumps(validation, indent=2))

# ---------------------------------------------------------------------------
# Archive staging tables — rename with datestamp, never delete
# ---------------------------------------------------------------------------
print("")
print(f"==> Archiving staging tables (renaming with _{datestamp} suffix)...")

cur.execute(f"ALTER TABLE migration.trades RENAME TO trades_{datestamp}")
cur.execute(f"ALTER TABLE migration.recommendation_log RENAME TO recommendation_log_{datestamp}")
conn.commit()

print(f"  migration.trades             → migration.trades_{datestamp}")
print(f"  migration.recommendation_log → migration.recommendation_log_{datestamp}")
print("")
print("  Staging data is archived, not deleted.")
print(f"  To inspect: SELECT * FROM migration.trades_{datestamp} LIMIT 5;")
print(f"  To remove later (when confident): DROP TABLE migration.trades_{datestamp};")

conn.close()

print("")
print("============================================================")
print(" Migration complete.")
print(f" Audit trail: {validation_path}")
print(" Run: sudo bash infra/08_healthcheck.sh")
print("============================================================")
PYEOF
