#!/usr/bin/env bash
# Step 2 of 3 — Load Turso export into migration.* staging tables in PostgreSQL.
#
# This loads data into migration.trades and migration.recommendation_log —
# NOT into the live zerodha.* and journal.* tables yet. You can inspect,
# validate, and re-run this step as many times as needed before committing.
#
# Prerequisites:
#   - infra/turso_migration/01_export_turso.sh has been run
#   - PostgreSQL is running with alembic upgrade head already applied
#   - The migration schema staging tables exist (0002 migration)
#
# Usage:
#   bash infra/turso_migration/02_stage_to_postgres.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPORT_DIR="${SCRIPT_DIR}/export"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="/etc/zerodha-mcp/.env"

if [ -f "${ENV_FILE}" ]; then
  set -a; source "${ENV_FILE}"; set +a
elif [ -f ".env" ]; then
  set -a; source ".env"; set +a
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL is not set."
  exit 1
fi

if [ ! -f "${EXPORT_DIR}/trades.json" ] || [ ! -f "${EXPORT_DIR}/recommendation_log.json" ]; then
  echo "ERROR: Export files not found in ${EXPORT_DIR}/"
  echo "Run first: bash infra/turso_migration/01_export_turso.sh"
  exit 1
fi

TRADES_COUNT=$(python3 -c "import json; print(len(json.load(open('${EXPORT_DIR}/trades.json'))))")
REC_COUNT=$(python3 -c "import json; print(len(json.load(open('${EXPORT_DIR}/recommendation_log.json'))))")

echo "============================================================"
echo " Stage Turso data → migration.* (PostgreSQL)"
echo " trades              : ${TRADES_COUNT} rows"
echo " recommendation_log  : ${REC_COUNT} rows"
echo "============================================================"
echo ""

cd "${REPO_ROOT}"

uv run python3 - <<'PYEOF'
import json
import os
from pathlib import Path

# Parse DATABASE_URL into psycopg2-compatible kwargs
db_url = os.environ["DATABASE_URL"]
# Strip asyncpg driver prefix if present
db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

import psycopg2
import psycopg2.extras

script_dir = Path(__file__).parent
export_dir = script_dir / "export"

conn = psycopg2.connect(db_url)
conn.autocommit = False
cur = conn.cursor()

# ---------------------------------------------------------------------------
# Truncate staging tables before loading (idempotent re-runs)
# ---------------------------------------------------------------------------
print("==> Clearing migration.trades staging table...")
cur.execute("TRUNCATE migration.trades")
print("==> Clearing migration.recommendation_log staging table...")
cur.execute("TRUNCATE migration.recommendation_log")
conn.commit()

# ---------------------------------------------------------------------------
# Load trades
# ---------------------------------------------------------------------------
print("==> Loading trades into migration.trades...")
with open(export_dir / "trades.json") as f:
    trades = json.load(f)

def coerce_float(v):
    if v in (None, "", "None", "null"): return None
    try: return float(v)
    except: return None

def coerce_int(v):
    if v in (None, "", "None", "null"): return None
    try: return int(v)
    except: return None

def coerce_str(v):
    if v in (None, "", "None", "null"): return None
    return str(v)

inserted = 0
skipped = 0
for row in trades:
    try:
        cur.execute("""
            INSERT INTO migration.trades (
                id, symbol, trade_type, direction, strategy,
                entry_price, quantity, entry_date, entry_time, rationale,
                stoploss, target, risk_reward, regime, signal, risk_score,
                analysis_snapshot, created_by, status,
                exit_price, exit_date, exit_time, exit_reason,
                pnl, pnl_percent, holding_days, tags, notes,
                risk_amount, capital_at_risk, portfolio_heat_at_entry,
                external_id, created_at, updated_at, user_id
            ) VALUES (
                %(id)s, %(symbol)s, %(trade_type)s, %(direction)s, %(strategy)s,
                %(entry_price)s, %(quantity)s, %(entry_date)s, %(entry_time)s, %(rationale)s,
                %(stoploss)s, %(target)s, %(risk_reward)s, %(regime)s, %(signal)s, %(risk_score)s,
                %(analysis_snapshot)s, %(created_by)s, %(status)s,
                %(exit_price)s, %(exit_date)s, %(exit_time)s, %(exit_reason)s,
                %(pnl)s, %(pnl_percent)s, %(holding_days)s, %(tags)s, %(notes)s,
                %(risk_amount)s, %(capital_at_risk)s, %(portfolio_heat_at_entry)s,
                %(external_id)s, %(created_at)s, %(updated_at)s, %(user_id)s
            ) ON CONFLICT (id) DO NOTHING
        """, {
            "id":                      coerce_str(row.get("id")),
            "symbol":                  coerce_str(row.get("symbol")),
            "trade_type":              coerce_str(row.get("trade_type")) or "EQUITY",
            "direction":               coerce_str(row.get("direction")),
            "strategy":                coerce_str(row.get("strategy")),
            "entry_price":             coerce_float(row.get("entry_price")),
            "quantity":                coerce_int(row.get("quantity")),
            "entry_date":              coerce_str(row.get("entry_date")),
            "entry_time":              coerce_str(row.get("entry_time")),
            "rationale":               coerce_str(row.get("rationale")),
            "stoploss":                coerce_float(row.get("stoploss")),
            "target":                  coerce_float(row.get("target")),
            "risk_reward":             coerce_float(row.get("risk_reward")),
            "regime":                  coerce_str(row.get("regime")),
            "signal":                  coerce_str(row.get("signal")),
            "risk_score":              coerce_int(row.get("risk_score")),
            "analysis_snapshot":       coerce_str(row.get("analysis_snapshot")),
            "created_by":              coerce_str(row.get("created_by")) or "MANUAL",
            "status":                  coerce_str(row.get("status")) or "OPEN",
            "exit_price":              coerce_float(row.get("exit_price")),
            "exit_date":               coerce_str(row.get("exit_date")),
            "exit_time":               coerce_str(row.get("exit_time")),
            "exit_reason":             coerce_str(row.get("exit_reason")),
            "pnl":                     coerce_float(row.get("pnl")),
            "pnl_percent":             coerce_float(row.get("pnl_percent")),
            "holding_days":            coerce_int(row.get("holding_days")),
            "tags":                    coerce_str(row.get("tags")),
            "notes":                   coerce_str(row.get("notes")),
            "risk_amount":             coerce_float(row.get("risk_amount")),
            "capital_at_risk":         coerce_float(row.get("capital_at_risk")),
            "portfolio_heat_at_entry": coerce_float(row.get("portfolio_heat_at_entry")),
            "external_id":             coerce_str(row.get("external_id")),
            "created_at":              coerce_str(row.get("created_at")),
            "updated_at":              coerce_str(row.get("updated_at")),
            "user_id":                 coerce_str(row.get("user_id")),
        })
        inserted += 1
    except Exception as e:
        print(f"  WARN: skipping trade {row.get('id')}: {e}")
        skipped += 1

conn.commit()
print(f"  trades staged: {inserted} inserted, {skipped} skipped")

# ---------------------------------------------------------------------------
# Load recommendation_log
# ---------------------------------------------------------------------------
print("==> Loading recommendation_log into migration.recommendation_log...")
with open(export_dir / "recommendation_log.json") as f:
    recs = json.load(f)

inserted = 0
skipped = 0
for row in recs:
    try:
        cur.execute("""
            INSERT INTO migration.recommendation_log (
                id, timestamp, symbol, market_snapshot, mcp_facts,
                user_action, outcome_1d, outcome_5d, outcome_20d,
                claude_reasoning_summary, recommendation_type, uncertainty_level,
                mcp_changed_decision, would_have_acted_without_mcp,
                decision_quality, postmortem_helpful, postmortem_why,
                postmortem_review_questions, bootstrap_period, bias_contaminated,
                baseline_no_mcp, capture_mode, created_at, updated_at, user_id
            ) VALUES (
                %(id)s, %(timestamp)s, %(symbol)s, %(market_snapshot)s, %(mcp_facts)s,
                %(user_action)s, %(outcome_1d)s, %(outcome_5d)s, %(outcome_20d)s,
                %(claude_reasoning_summary)s, %(recommendation_type)s, %(uncertainty_level)s,
                %(mcp_changed_decision)s, %(would_have_acted_without_mcp)s,
                %(decision_quality)s, %(postmortem_helpful)s, %(postmortem_why)s,
                %(postmortem_review_questions)s, %(bootstrap_period)s, %(bias_contaminated)s,
                %(baseline_no_mcp)s, %(capture_mode)s, %(created_at)s, %(updated_at)s, %(user_id)s
            ) ON CONFLICT (id) DO NOTHING
        """, {
            "id":                           coerce_str(row.get("id")),
            "timestamp":                    coerce_str(row.get("timestamp")),
            "symbol":                       coerce_str(row.get("symbol")),
            "market_snapshot":              coerce_str(row.get("market_snapshot")),
            "mcp_facts":                    coerce_str(row.get("mcp_facts")),
            "user_action":                  coerce_str(row.get("user_action")),
            "outcome_1d":                   coerce_float(row.get("outcome_1d")),
            "outcome_5d":                   coerce_float(row.get("outcome_5d")),
            "outcome_20d":                  coerce_float(row.get("outcome_20d")),
            "claude_reasoning_summary":     coerce_str(row.get("claude_reasoning_summary")),
            "recommendation_type":          coerce_str(row.get("recommendation_type")),
            "uncertainty_level":            coerce_str(row.get("uncertainty_level")),
            "mcp_changed_decision":         coerce_int(row.get("mcp_changed_decision")),
            "would_have_acted_without_mcp": coerce_int(row.get("would_have_acted_without_mcp")),
            "decision_quality":             coerce_str(row.get("decision_quality")),
            "postmortem_helpful":           coerce_int(row.get("postmortem_helpful")),
            "postmortem_why":               coerce_str(row.get("postmortem_why")),
            "postmortem_review_questions":  coerce_str(row.get("postmortem_review_questions")),
            "bootstrap_period":             coerce_int(row.get("bootstrap_period")) if row.get("bootstrap_period") is not None else 1,
            "bias_contaminated":            coerce_int(row.get("bias_contaminated")) if row.get("bias_contaminated") is not None else 1,
            "baseline_no_mcp":              coerce_int(row.get("baseline_no_mcp")) if row.get("baseline_no_mcp") is not None else 0,
            "capture_mode":                 coerce_str(row.get("capture_mode")) or "manual",
            "created_at":                   coerce_str(row.get("created_at")),
            "updated_at":                   coerce_str(row.get("updated_at")),
            "user_id":                      coerce_str(row.get("user_id")),
        })
        inserted += 1
    except Exception as e:
        print(f"  WARN: skipping recommendation {row.get('id')}: {e}")
        skipped += 1

conn.commit()
print(f"  recommendation_log staged: {inserted} inserted, {skipped} skipped")

# ---------------------------------------------------------------------------
# Validation counts
# ---------------------------------------------------------------------------
cur.execute("SELECT COUNT(*) FROM migration.trades")
staged_trades = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM migration.recommendation_log")
staged_recs = cur.fetchone()[0]

print("")
print("=== Staging validation ===")
print(f"  migration.trades             : {staged_trades} rows")
print(f"  migration.recommendation_log : {staged_recs} rows")

conn.close()
print("")
print("Staging complete.")
print("Next: inspect data, then run bash infra/turso_migration/03_promote_to_production.sh")
PYEOF
