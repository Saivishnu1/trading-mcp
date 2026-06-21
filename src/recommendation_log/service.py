"""
Phase 22 — Recommendation decision-quality logger.

Answers the one question that matters:
  "Does using this MCP improve my trading decision quality?"

NOT "does it predict the market" — that's the wrong question.

Partition constants:
  BOOTSTRAP_PERIOD_RECORDS      — first N records are bootstrap (high bias)
  BASELINE_RECORDS_REQUIRED     — baseline (no-MCP) records needed for 2x2 table
  MIN_CLEAN_RECORDS_FOR_ANALYSIS — minimum clean records before stats are meaningful

Schema lives in src/journal/db.py (recommendation_log table, v4).
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

from src.journal import db as _db
from src.broker import current_user


def _uid() -> str | None:
    return current_user.get()


def _user_filter(params: list) -> str:
    uid = _uid()
    if uid:
        params.append(uid)
        return "user_id = ?"
    return "1=0"  # unauthenticated: return nothing

_WRITE_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Partition constants
# ---------------------------------------------------------------------------

BOOTSTRAP_PERIOD_RECORDS = 50
BASELINE_RECORDS_REQUIRED = 10
MIN_CLEAN_RECORDS_FOR_ANALYSIS = 100


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _new_id() -> str:
    return "REC-" + uuid.uuid4().hex[:8]


def _json_or_none(obj) -> str | None:
    if obj is None:
        return None
    return json.dumps(obj)


def _parse_json(s: str | None):
    if s is None:
        return None
    try:
        return json.loads(s)
    except Exception:
        return s


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    d = dict(row) if not isinstance(row, dict) else row
    for json_field in ("market_snapshot", "mcp_facts", "decision_quality",
                       "postmortem_review_questions"):
        if json_field in d:
            d[json_field] = _parse_json(d[json_field])
    for bool_field in ("mcp_changed_decision", "would_have_acted_without_mcp",
                       "postmortem_helpful", "bootstrap_period",
                       "bias_contaminated", "baseline_no_mcp"):
        if bool_field in d and d[bool_field] is not None:
            d[bool_field] = bool(d[bool_field])
    return d


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def log_recommendation(
    symbol: str | None,
    user_question: str,
    market_snapshot: dict | None,
    mcp_facts: dict | None,
    claude_reasoning_summary: str,
    recommendation_type: str,
    uncertainty_level: str,
    baseline_no_mcp: bool = False,
) -> dict:
    """Create a new recommendation record.

    All outcome fields are NULL — filled during weekly review.
    bootstrap_period=1 and bias_contaminated=1 by default.
    Returns the full record with its id.
    """
    valid_types = {
        "ENTER", "EXIT", "HOLD", "AVOID", "OBSERVE",
        "STAY_CASH", "SIZE_REDUCE", "TAKE_PROFIT", "TIGHTEN_STOP", "NONE",
    }
    valid_uncertainty = {"LOW", "MEDIUM", "HIGH"}

    rec_type = (recommendation_type or "").upper().strip()
    unc_level = (uncertainty_level or "").upper().strip()

    if rec_type not in valid_types:
        return {"error": f"Invalid recommendation_type '{rec_type}'. Valid: {sorted(valid_types)}"}
    if unc_level not in valid_uncertainty:
        return {"error": f"Invalid uncertainty_level '{unc_level}'. Valid: {sorted(valid_uncertainty)}"}

    rec_id = _new_id()
    now = _now_utc()

    with _WRITE_LOCK:
        conn = _db._get_connection()
        conn.execute(
            """
            INSERT INTO recommendation_log (
                id, timestamp, symbol, market_snapshot, mcp_facts,
                claude_reasoning_summary, recommendation_type, uncertainty_level,
                baseline_no_mcp, bootstrap_period, bias_contaminated,
                capture_mode, created_at, updated_at, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?)
            """,
            (
                rec_id, now,
                symbol.upper().strip() if symbol else None,
                _json_or_none(market_snapshot),
                _json_or_none(mcp_facts),
                claude_reasoning_summary,
                rec_type, unc_level,
                1 if baseline_no_mcp else 0,
                "baseline" if baseline_no_mcp else "manual",
                now, now, _uid(),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM recommendation_log WHERE id = ?", (rec_id,)
        ).fetchone()

    return _row_to_dict(row)


def update_recommendation_outcome(
    id: str,
    user_action: str | None = None,
    mcp_changed_decision: bool | None = None,
    would_have_acted_without_mcp: bool | None = None,
    decision_quality: dict | None = None,
    outcome_1d: float | None = None,
    outcome_5d: float | None = None,
    outcome_20d: float | None = None,
    postmortem_helpful: bool | None = None,
    postmortem_why: str | None = None,
    postmortem_review_questions: dict | None = None,
) -> dict:
    """Update outcome and postmortem fields on an existing record.

    Called during weekly blind review — NOT at trade time.
    Only updates fields that are explicitly passed (non-None).
    """
    conn = _db._get_connection()
    row = conn.execute(
        "SELECT id FROM recommendation_log WHERE id = ?", (id,)
    ).fetchone()
    if not row:
        return {"error": f"Record not found: {id}"}

    updates: list[tuple] = []
    if user_action is not None:
        updates.append(("user_action", user_action))
    if mcp_changed_decision is not None:
        updates.append(("mcp_changed_decision", 1 if mcp_changed_decision else 0))
    if would_have_acted_without_mcp is not None:
        updates.append(("would_have_acted_without_mcp", 1 if would_have_acted_without_mcp else 0))
    if decision_quality is not None:
        updates.append(("decision_quality", _json_or_none(decision_quality)))
    if outcome_1d is not None:
        updates.append(("outcome_1d", outcome_1d))
    if outcome_5d is not None:
        updates.append(("outcome_5d", outcome_5d))
    if outcome_20d is not None:
        updates.append(("outcome_20d", outcome_20d))
    if postmortem_helpful is not None:
        updates.append(("postmortem_helpful", 1 if postmortem_helpful else 0))
    if postmortem_why is not None:
        updates.append(("postmortem_why", postmortem_why))
    if postmortem_review_questions is not None:
        updates.append(("postmortem_review_questions", _json_or_none(postmortem_review_questions)))

    if not updates:
        return {"error": "No fields provided to update."}

    now = _now_utc()
    updates.append(("updated_at", now))

    set_clause = ", ".join(f"{col} = ?" for col, _ in updates)
    values = [v for _, v in updates] + [id]

    with _WRITE_LOCK:
        conn.execute(
            f"UPDATE recommendation_log SET {set_clause} WHERE id = ?", values
        )
        conn.commit()
        updated_row = conn.execute(
            "SELECT * FROM recommendation_log WHERE id = ?", (id,)
        ).fetchone()

    return _row_to_dict(updated_row)


def get_recommendation_stats(clean_only: bool = True) -> dict:
    """Return counts and readiness status across all partitions.

    Refuses to return statistical analysis before MIN_CLEAN_RECORDS.
    """
    conn = _db._get_connection()
    params: list = []
    uf = _user_filter(params)

    def _count(extra: str = "") -> int:
        where = f"WHERE {uf}" + (f" AND {extra}" if extra else "")
        row = conn.execute(f"SELECT COUNT(*) as n FROM recommendation_log {where}", params).fetchone()
        return row["n"] if isinstance(row, dict) else (row[0] if row else 0)

    total_count = _count()
    clean_count = _count("bootstrap_period=0 AND bias_contaminated=0")
    bootstrap_count = _count("bootstrap_period=1 OR bias_contaminated=1")
    baseline_count = _count("baseline_no_mcp=1")

    analysis_ready = (
        clean_count >= MIN_CLEAN_RECORDS_FOR_ANALYSIS
        and baseline_count >= BASELINE_RECORDS_REQUIRED
    )
    records_until_clean = max(0, MIN_CLEAN_RECORDS_FOR_ANALYSIS - clean_count)
    records_until_baseline = max(0, BASELINE_RECORDS_REQUIRED - baseline_count)

    result: dict = {
        "total_records": total_count,
        "clean_records": clean_count,
        "bootstrap_records": bootstrap_count,
        "baseline_records": baseline_count,
        "analysis_ready": analysis_ready,
        "records_until_clean_analysis": records_until_clean,
        "records_until_baseline": records_until_baseline,
        "thresholds": {
            "bootstrap_period_records": BOOTSTRAP_PERIOD_RECORDS,
            "baseline_records_required": BASELINE_RECORDS_REQUIRED,
            "min_clean_records_for_analysis": MIN_CLEAN_RECORDS_FOR_ANALYSIS,
        },
        "stats": None,
    }

    if analysis_ready and not clean_only:
        result["stats"] = _compute_stats(conn, uf, params)

    return result


def _compute_stats(conn, uf: str, params: list) -> dict:
    """Compute clean-record statistics. Only called after MIN_CLEAN_RECORDS met."""
    rows = conn.execute(
        f"""
        SELECT mcp_changed_decision, would_have_acted_without_mcp,
               postmortem_helpful, outcome_1d, outcome_5d, outcome_20d
        FROM recommendation_log
        WHERE {uf} AND bootstrap_period=0 AND bias_contaminated=0
        """,
        params,
    ).fetchall()

    changed = sum(1 for r in rows if (r["mcp_changed_decision"] if isinstance(r, dict) else r[0]) == 1)
    helpful = sum(1 for r in rows if (r["postmortem_helpful"] if isinstance(r, dict) else r[2]) == 1)
    reviewed = sum(1 for r in rows if (r["postmortem_helpful"] if isinstance(r, dict) else r[2]) is not None)
    n = len(rows)

    return {
        "n": n,
        "mcp_changed_decision_rate": round(changed / n, 3) if n else None,
        "postmortem_helpful_rate": round(helpful / reviewed, 3) if reviewed else None,
        "reviewed_count": reviewed,
    }


def get_recommendation_by_id(id: str) -> dict:
    conn = _db._get_connection()
    row = conn.execute(
        "SELECT * FROM recommendation_log WHERE id = ?", (id,)
    ).fetchone()
    if not row:
        return {"error": f"Record not found: {id}"}
    return _row_to_dict(row)
