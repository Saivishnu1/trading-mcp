import json
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

from src.journal import db as _db

_WRITE_LOCK = threading.Lock()

VALID_EXIT_REASONS: frozenset[str] = frozenset({
    "TARGET_HIT",
    "STOPLOSS_HIT",
    "MANUAL",
    "THESIS_INVALIDATED",
    "EXPIRED",
    "CANCELLED",
})

VALID_DIRECTIONS: frozenset[str] = frozenset({"LONG", "SHORT"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _today() -> str:
    return date.today().isoformat()


def _new_trade_id() -> str:
    return "TRD-" + uuid.uuid4().hex[:8]


def _calculate_pnl(
    direction: str, entry_price: float, exit_price: float, quantity: int | None
) -> tuple[float, float]:
    qty = quantity or 1
    if direction == "LONG":
        pnl = (exit_price - entry_price) * qty
        pnl_pct = (exit_price - entry_price) / entry_price * 100
    else:
        pnl = (entry_price - exit_price) * qty
        pnl_pct = (entry_price - exit_price) / entry_price * 100
    return round(pnl, 2), round(pnl_pct, 2)


def _auto_risk_reward(
    direction: str, entry: float, stoploss: float, target: float
) -> float | None:
    if direction == "LONG":
        risk = entry - stoploss
        reward = target - entry
    else:
        risk = stoploss - entry
        reward = entry - target
    if risk <= 0:
        return None
    return round(reward / risk, 2)


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["trade_id"] = d.pop("id")
    if d.get("tags"):
        try:
            d["tags"] = json.loads(d["tags"])
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
    else:
        d["tags"] = []
    if d.get("analysis_snapshot"):
        try:
            d["analysis_snapshot"] = json.loads(d["analysis_snapshot"])
        except (json.JSONDecodeError, TypeError):
            d["analysis_snapshot"] = None
    return d


def _build_summary(trades: list[dict]) -> dict:
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    open_trades = [t for t in trades if t.get("status") == "OPEN"]
    wins = [t for t in closed if (t.get("pnl") or 0) > 0]
    losses = [t for t in closed if (t.get("pnl") or 0) <= 0]

    total_pnl = round(sum(t["pnl"] for t in closed if t.get("pnl") is not None), 2)
    avg_pnl = round(total_pnl / len(closed), 2) if closed else 0.0

    h_days = [t["holding_days"] for t in closed if t.get("holding_days") is not None]
    avg_holding_days = round(sum(h_days) / len(h_days), 1) if h_days else 0.0

    win_rate_pct = round(len(wins) / len(closed) * 100, 1) if closed else 0.0

    best = max(closed, key=lambda t: t.get("pnl") or float("-inf")) if closed else None
    worst = min(closed, key=lambda t: t.get("pnl") or float("inf")) if closed else None

    return {
        "total_trades": len(trades),
        "open_trades": len(open_trades),
        "closed_trades": len(closed),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": win_rate_pct,
        "total_pnl": total_pnl,
        "avg_pnl": avg_pnl,
        "avg_holding_days": avg_holding_days,
        "best_trade": (
            {"trade_id": best["trade_id"], "symbol": best["symbol"], "pnl": best["pnl"]}
            if best else None
        ),
        "worst_trade": (
            {"trade_id": worst["trade_id"], "symbol": worst["symbol"], "pnl": worst["pnl"]}
            if worst else None
        ),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def log_trade(
    symbol: str,
    direction: str,
    entry_price: float,
    quantity: int | None = None,
    strategy: str | None = None,
    rationale: str | None = None,
    stoploss: float | None = None,
    target: float | None = None,
    risk_reward: float | None = None,
    regime: str | None = None,
    signal: str | None = None,
    risk_score: int | None = None,
    analysis_snapshot: dict | None = None,
    trade_type: str = "EQUITY",
    created_by: str = "MANUAL",
    tags: list[str] | None = None,
    notes: str | None = None,
    risk_amount: float | None = None,
    capital_at_risk: float | None = None,
    portfolio_heat_at_entry: float | None = None,
) -> dict:
    try:
        direction = direction.upper().strip()
        if direction not in VALID_DIRECTIONS:
            return {"error": "direction must be LONG or SHORT"}
        if entry_price <= 0:
            return {"error": "entry_price must be positive"}
        if risk_score is not None and not (0 <= risk_score <= 100):
            return {"error": "risk_score must be between 0 and 100"}

        symbol = symbol.upper().strip()
        trade_type = trade_type.upper().strip()
        created_by = created_by.upper().strip()

        rr = risk_reward
        if rr is None and stoploss is not None and target is not None:
            rr = _auto_risk_reward(direction, entry_price, stoploss, target)

        now = _now_utc()
        today = _today()
        trade_id = _new_trade_id()

        tags_json = json.dumps(tags) if tags is not None else None
        snapshot_json = json.dumps(analysis_snapshot) if analysis_snapshot is not None else None

        conn = _db._get_connection()
        with _WRITE_LOCK:
            conn.execute(
                """INSERT INTO trades (
                    id, symbol, trade_type, direction, strategy,
                    entry_price, quantity, entry_date, entry_time,
                    rationale, stoploss, target, risk_reward,
                    regime, signal, risk_score, analysis_snapshot,
                    created_by, status, tags, notes,
                    risk_amount, capital_at_risk, portfolio_heat_at_entry,
                    created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, 'OPEN', ?, ?,
                    ?, ?, ?,
                    ?, ?
                )""",
                (
                    trade_id, symbol, trade_type, direction, strategy,
                    entry_price, quantity, today, now,
                    rationale, stoploss, target, rr,
                    regime, signal, risk_score, snapshot_json,
                    created_by, tags_json, notes,
                    risk_amount, capital_at_risk, portfolio_heat_at_entry,
                    now, now,
                ),
            )
            conn.commit()

        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        return _row_to_dict(row)
    except Exception as exc:
        return {"error": str(exc)}


def close_trade(
    trade_id: str,
    exit_price: float,
    exit_reason: str = "MANUAL",
    notes: str | None = None,
) -> dict:
    try:
        exit_reason = exit_reason.upper().strip()
        if exit_reason not in VALID_EXIT_REASONS:
            return {
                "error": (
                    f"exit_reason must be one of: "
                    f"{', '.join(sorted(VALID_EXIT_REASONS))}"
                )
            }

        conn = _db._get_connection()
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if row is None:
            return {"error": f"trade not found: {trade_id}"}

        trade = dict(row)
        if trade["status"] == "CLOSED":
            return {"error": "trade already closed"}

        pnl, pnl_pct = _calculate_pnl(
            trade["direction"], trade["entry_price"], exit_price, trade["quantity"]
        )

        entry_d = date.fromisoformat(trade["entry_date"])
        holding_days = (date.today() - entry_d).days

        existing_notes = trade.get("notes") or ""
        if notes:
            new_notes = (existing_notes + "\n" + notes).strip() if existing_notes else notes
        else:
            new_notes = existing_notes or None

        now = _now_utc()
        today = _today()

        with _WRITE_LOCK:
            conn.execute(
                """UPDATE trades SET
                    status       = 'CLOSED',
                    exit_price   = ?,
                    exit_date    = ?,
                    exit_time    = ?,
                    exit_reason  = ?,
                    pnl          = ?,
                    pnl_percent  = ?,
                    holding_days = ?,
                    notes        = ?,
                    updated_at   = ?
                WHERE id = ?""",
                (
                    exit_price, today, now, exit_reason,
                    pnl, pnl_pct, holding_days, new_notes, now,
                    trade_id,
                ),
            )
            conn.commit()

        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        return _row_to_dict(row)
    except Exception as exc:
        return {"error": str(exc)}


def get_open_trades(symbol: str | None = None) -> dict:
    try:
        conn = _db._get_connection()
        if symbol:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status = 'OPEN' AND symbol = ?"
                " ORDER BY entry_date DESC, created_at DESC",
                (symbol.upper().strip(),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status = 'OPEN'"
                " ORDER BY entry_date DESC, created_at DESC"
            ).fetchall()
        trades = [_row_to_dict(r) for r in rows]
        return {"count": len(trades), "trades": trades}
    except Exception as exc:
        return {"error": str(exc)}


def get_trade_history(
    symbol: str | None = None,
    days: int = 30,
    status: str | None = None,
    limit: int = 50,
) -> dict:
    try:
        cutoff = (date.today() - timedelta(days=max(days, 0))).isoformat()
        conditions = ["entry_date >= ?"]
        params: list = [cutoff]

        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol.upper().strip())

        if status:
            conditions.append("status = ?")
            params.append(status.upper().strip())

        where = " AND ".join(conditions)
        params.append(max(limit, 1))

        conn = _db._get_connection()
        rows = conn.execute(
            f"SELECT * FROM trades WHERE {where}"
            " ORDER BY entry_date DESC, created_at DESC LIMIT ?",
            params,
        ).fetchall()

        trades = [_row_to_dict(r) for r in rows]
        return {
            "count": len(trades),
            "filters": {
                "symbol": symbol.upper().strip() if symbol else None,
                "days": days,
                "status": status.upper().strip() if status else None,
                "limit": limit,
            },
            "trades": trades,
            "summary": _build_summary(trades),
        }
    except Exception as exc:
        return {"error": str(exc)}
