import json
import re
import threading
import uuid
from datetime import UTC, date, datetime, timedelta

from src.broker import current_user
from src.journal import db as _db


def _uid() -> str | None:
    return current_user.get()

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

def _user_filter(params: list) -> str:
    """Return SQL fragment scoping to the current user. No user = no data."""
    uid = _uid()
    if uid:
        params.append(uid)
        return "user_id = ?"
    return "1=0"  # unauthenticated: return nothing


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")


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
    external_id: str | None = None,
    entry_date: str | None = None,
    entry_time: str | None = None,
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

        # Priority B4 (2026-07-11) — computed BEFORE inserting the new trade,
        # since detect_reentry_pattern counts existing same-strike trades and
        # treats this one as "+1" itself. Observational only — never blocks.
        reentry_warning = detect_reentry_pattern(symbol)

        now = _now_utc()
        entry_d = entry_date if entry_date is not None else _today()
        entry_t = entry_time if entry_time is not None else now
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
                    external_id, created_at, updated_at, user_id
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, 'OPEN', ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?
                )""",
                (
                    trade_id, symbol, trade_type, direction, strategy,
                    entry_price, quantity, entry_d, entry_t,
                    rationale, stoploss, target, rr,
                    regime, signal, risk_score, snapshot_json,
                    created_by, tags_json, notes,
                    risk_amount, capital_at_risk, portfolio_heat_at_entry,
                    external_id, now, now, _uid(),
                ),
            )
            conn.commit()

        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        result = _row_to_dict(row)
        if reentry_warning is not None:
            result["REENTRY_WARNING"] = reentry_warning
        return result
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Re-entry pattern detection + strike-level attempt tally (Priorities B4/B5,
# 2026-07-11) — observational only, per the task's explicit "no auto-reject"
# scope. Grouping key is (underlying, strike, option_type) parsed from the
# free-text symbol column — there's no separate strike/option_type column in
# this SQLite schema (trades.symbol carries the full option identifier).
# ---------------------------------------------------------------------------

_LOOSE_OPTION_RE = re.compile(
    r"^([A-Z]+)\D*?(\d+(?:\.\d+)?)\s*(CE|PE)$"
)


def _parse_option_symbol(symbol: str) -> tuple[str, float, str] | None:
    """Best-effort (underlying, strike, option_type) extraction. Reuses the
    Zerodha tradingsymbol parser (src/monitor/symbol_resolver.py) for the
    exact NFO format real synced trades carry, with a permissive fallback
    for other input shapes (e.g. "NIFTY 24200 CE" from manual log_trade
    calls). Returns None for anything unparseable — callers must skip those
    rows from strike-level grouping rather than guess."""
    from src.monitor.symbol_resolver import _parse_zerodha_tradingsymbol

    parsed = _parse_zerodha_tradingsymbol(symbol)
    if parsed:
        return parsed["symbol"], parsed["strike"], parsed["option_type"]

    m = _LOOSE_OPTION_RE.match(symbol.upper().strip().replace(" ", ""))
    if m:
        underlying, strike, opt = m.groups()
        return underlying, float(strike), opt
    return None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _todays_trades() -> list[dict]:
    """All of today's trades for the current user, any status — the shared
    fetch both detect_reentry_pattern and get_strike_attempts build on."""
    params: list = []
    uf = _user_filter(params)
    params.append(_today())
    conn = _db._get_connection()
    rows = conn.execute(
        f"SELECT * FROM trades WHERE {uf} AND entry_date = ? ORDER BY created_at ASC",
        params,
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def detect_reentry_pattern(
    new_trade_symbol: str, window_minutes: int = 120,
) -> str | None:
    """Observational-only re-entry warning for log_trade — never blocks or
    rejects. Returns a REENTRY_WARNING string, or None when no pattern is
    detected (including when new_trade_symbol doesn't parse as an option).

    Fires when either:
      - this is the 3rd+ entry into the same underlying+strike+option_type
        within the last `window_minutes`, or
      - the most recent entry on that exact strike closed at a loss within
        the last 30 minutes (a loss-recovery re-entry, regardless of count).
    """
    parsed = _parse_option_symbol(new_trade_symbol)
    if parsed is None:
        return None
    underlying, strike, opt = parsed

    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=window_minutes)

    same_strike = [
        t for t in _todays_trades()
        if _parse_option_symbol(t["symbol"]) == parsed
    ]
    recent = [t for t in same_strike if (_parse_dt(t.get("entry_time")) or cutoff) >= cutoff]

    label = f"{underlying} {strike:g} {opt}"
    warnings: list[str] = []

    count_including_new = len(recent) + 1
    if count_including_new >= 3:
        warnings.append(
            f"{count_including_new}th entry into {label} in the last {window_minutes} minutes."
        )

    most_recent_closed = max(
        (t for t in same_strike if t.get("status") == "CLOSED"),
        key=lambda t: _parse_dt(t.get("exit_time")) or datetime.min.replace(tzinfo=UTC),
        default=None,
    )
    if most_recent_closed is not None:
        exit_dt = _parse_dt(most_recent_closed.get("exit_time"))
        pnl = most_recent_closed.get("pnl")
        if exit_dt is not None and pnl is not None and pnl < 0 and (now - exit_dt) <= timedelta(minutes=30):
            minutes_ago = int((now - exit_dt).total_seconds() // 60)
            warnings.append(
                f"Most recent entry on {label} closed at -₹{abs(pnl):.2f} "
                f"{minutes_ago} minutes ago."
            )

    if not warnings:
        return None
    return "REENTRY_WARNING: " + " ".join(warnings)


def get_strike_attempts(underlying: str | None = None) -> dict:
    """Today's strike-level attempt tally — read-only aggregation over
    today's trades, grouped by (underlying, strike, option_type), regardless
    of whether the trader re-entered every time (Priority B5). Optionally
    filtered to one underlying (e.g. "NIFTY")."""
    try:
        groups: dict[tuple[str, float, str], list[dict]] = {}
        for t in _todays_trades():
            parsed = _parse_option_symbol(t["symbol"])
            if parsed is None:
                continue
            if underlying and parsed[0] != underlying.upper().strip():
                continue
            groups.setdefault(parsed, []).append(t)

        strikes = []
        for (u, strike, opt), trades in groups.items():
            closed = [t for t in trades if t.get("status") == "CLOSED"]
            wins = [t for t in closed if (t.get("pnl") or 0) > 0]
            losses = [t for t in closed if (t.get("pnl") or 0) <= 0]
            net_pnl = round(sum(t["pnl"] for t in closed if t.get("pnl") is not None), 2)
            strikes.append({
                "underlying": u,
                "strike": strike,
                "option_type": opt,
                "attempts": len(trades),
                "wins": len(wins),
                "losses": len(losses),
                "net_pnl": net_pnl,
                "summary": f"{u} {strike:g} {opt}: tested {len(trades)} times today, "
                           f"{len(wins)} wins / {len(losses)} losses, net {net_pnl:+.2f}.",
            })

        strikes.sort(key=lambda s: s["attempts"], reverse=True)
        return {"date": _today(), "underlying": underlying.upper().strip() if underlying else None, "strikes": strikes}
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
        params: list = []
        uf = _user_filter(params)
        if symbol:
            params.append(symbol.upper().strip())
            rows = conn.execute(
                f"SELECT * FROM trades WHERE status = 'OPEN' AND {uf} AND symbol = ?"
                " ORDER BY entry_date DESC, created_at DESC",
                params,
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM trades WHERE status = 'OPEN' AND {uf}"
                " ORDER BY entry_date DESC, created_at DESC",
                params,
            ).fetchall()
        trades = [_row_to_dict(r) for r in rows]
        return {"count": len(trades), "trades": trades}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Zerodha auto-import (Phase 16)
# ---------------------------------------------------------------------------

def _parse_order_timestamp(ts: str) -> tuple[str, str]:
    """Parse Zerodha timestamp '2024-06-19 10:30:00' → ('2024-06-19', '10:30:00')."""
    try:
        ts = ts.strip()
        if not ts:
            return _today(), _now_utc()
        sep = "T" if "T" in ts else " "
        parts = ts.split(sep, 1)
        return parts[0], parts[1] if len(parts) > 1 else _now_utc()
    except Exception:
        return _today(), _now_utc()


def _product_to_trade_type(product: str, symbol: str) -> str:
    sym = symbol.upper()
    # Options: symbol ends with CE/PE AND the char before is a digit (e.g. "24000CE", not "RELIANCE")
    if (sym.endswith("CE") or sym.endswith("PE")) and len(sym) > 2 and sym[-3].isdigit():
        return "OPTIONS"
    if sym.endswith("FUT"):
        return "FUTURES"
    return "EQUITY"


def _find_open_long_for_symbol(symbol: str) -> dict | None:
    conn = _db._get_connection()
    params: list = []
    uf = _user_filter(params)
    params.append(symbol.upper())
    row = conn.execute(
        f"SELECT * FROM trades WHERE {uf} AND symbol = ? AND direction = 'LONG' AND status = 'OPEN'"
        " ORDER BY created_at DESC LIMIT 1",
        params,
    ).fetchone()
    return _row_to_dict(row) if row else None


def sync_zerodha_orders(orders: list[dict]) -> dict:
    """Import Zerodha COMPLETE orders into the journal.

    BUY orders → log as LONG (skipped if external_id already imported).
    SELL orders → close most recent open LONG for that symbol; skipped if none found.
    Idempotent: safe to call multiple times for the same order list.
    """
    def _ts(o: dict) -> str:
        return o.get("order_timestamp") or o.get("exchange_timestamp") or ""

    imported, closed_trades, skipped, unmatched, errors = [], [], [], [], []

    for order in sorted(orders, key=_ts):
        try:
            status = (order.get("status") or "").upper()
            if status != "COMPLETE":
                skipped.append({"order_id": order.get("order_id"), "reason": f"status={status}"})
                continue

            order_id = str(order.get("order_id", "")).strip()
            symbol = (order.get("tradingsymbol") or "").upper().strip()
            txn = (order.get("transaction_type") or "").upper()
            avg_price = float(order.get("average_price") or 0)
            qty = int(order.get("filled_quantity") or order.get("quantity") or 0)
            product = order.get("product", "CNC")
            ts = order.get("order_timestamp") or order.get("exchange_timestamp") or ""

            if not order_id or not symbol or avg_price <= 0 or qty <= 0:
                skipped.append({"order_id": order_id, "reason": "missing/invalid fields"})
                continue

            entry_date, entry_time = _parse_order_timestamp(ts)
            trade_type = _product_to_trade_type(product, symbol)

            if txn == "BUY":
                conn = _db._get_connection()
                already = conn.execute(
                    "SELECT id FROM trades WHERE external_id = ?", (order_id,)
                ).fetchone()
                if already:
                    skipped.append({"order_id": order_id, "symbol": symbol, "reason": "already_imported"})
                    continue
                result = log_trade(
                    symbol=symbol, direction="LONG", entry_price=avg_price,
                    quantity=qty, trade_type=trade_type, created_by="ZERODHA_SYNC",
                    tags=["zerodha-import"], external_id=order_id,
                    entry_date=entry_date, entry_time=entry_time,
                )
                if "error" in result:
                    errors.append({"order_id": order_id, "symbol": symbol, "error": result["error"]})
                else:
                    imported.append({"order_id": order_id, "symbol": symbol, "trade_id": result["trade_id"], "price": avg_price, "qty": qty})

            elif txn == "SELL":
                open_long = _find_open_long_for_symbol(symbol)
                if open_long:
                    result = close_trade(
                        trade_id=open_long["trade_id"],
                        exit_price=avg_price,
                        exit_reason="MANUAL",
                        notes=f"zerodha_sync:{order_id}",
                    )
                    if "error" in result:
                        errors.append({"order_id": order_id, "symbol": symbol, "error": result["error"]})
                    else:
                        closed_trades.append({"order_id": order_id, "symbol": symbol, "trade_id": open_long["trade_id"], "pnl": result.get("pnl"), "exit_price": avg_price})
                else:
                    unmatched.append({"order_id": order_id, "symbol": symbol, "reason": "no_open_long_found"})

        except Exception as exc:
            errors.append({"order_id": order.get("order_id", "?"), "error": str(exc)})

    return {
        "imported": len(imported),
        "closed": len(closed_trades),
        "skipped": len(skipped),
        "unmatched_sells": len(unmatched),
        "errors": len(errors),
        "details": {
            "imported": imported,
            "closed": closed_trades,
            "skipped": skipped,
            "unmatched_sells": unmatched,
            "errors": errors,
        },
    }


# ---------------------------------------------------------------------------
# Performance analytics — realized-outcome feedback loop (Phase 15)
# ---------------------------------------------------------------------------

# Below this many trades, a bucket's win rate is noise, not signal.
_MIN_SAMPLE = 10


def _confidence_of(trade: dict) -> float | None:
    """Setup confidence recorded at entry, read from analysis_snapshot."""
    snap = trade.get("analysis_snapshot")
    if isinstance(snap, dict):
        c = snap.get("confidence")
        if isinstance(c, (int, float)):
            return float(c)
    return None


def _confidence_band(c: float | None) -> str:
    if c is None:
        return "unknown"
    if c >= 75:
        return "high (75-85)"
    if c >= 60:
        return "moderate (60-74)"
    return "low (<60)"


def _bucket_stats(trades: list[dict], min_sample: int) -> dict:
    n = len(trades)
    pnls = [t.get("pnl") or 0 for t in trades]
    wins = [p for p in pnls if p > 0]
    total = round(sum(pnls), 2)
    return {
        "trades": n,
        "wins": len(wins),
        "win_rate_pct": round(len(wins) / n * 100, 1) if n else 0.0,
        "avg_pnl": round(total / n, 2) if n else 0.0,
        "total_pnl": total,
        "low_sample": n < min_sample,
    }


def _profit_factor(trades: list[dict]) -> float | None:
    gains = sum(p for t in trades if (p := t.get("pnl") or 0) > 0)
    losses = sum(p for t in trades if (p := t.get("pnl") or 0) < 0)
    if losses == 0:
        return None  # no losing trades in sample — undefined
    return round(gains / abs(losses), 2)


def _group_stats(trades: list[dict], keyfn, min_sample: int) -> dict:
    groups: dict[str, list[dict]] = {}
    for t in trades:
        groups.setdefault(keyfn(t), []).append(t)
    return {k: _bucket_stats(v, min_sample) for k, v in groups.items()}


def _edge_notes(closed: list[dict], by_signal: dict, by_conf: dict, min_sample: int) -> list[str]:
    notes: list[str] = []
    n = len(closed)
    if n < min_sample:
        notes.append(
            f"Only {n} closed trade(s) — not enough to judge edge "
            f"(need >= {min_sample}). Treat all figures as preliminary."
        )
        return notes

    hi = by_conf.get("high (75-85)")
    lo = by_conf.get("low (<60)")
    if hi and lo and not hi["low_sample"] and not lo["low_sample"]:
        if hi["win_rate_pct"] <= lo["win_rate_pct"]:
            notes.append(
                "Confidence is NOT calibrated: high-confidence trades are not "
                f"winning more than low-confidence ones "
                f"({hi['win_rate_pct']}% vs {lo['win_rate_pct']}%)."
            )
        else:
            notes.append(
                "Confidence looks calibrated: high-confidence "
                f"{hi['win_rate_pct']}% vs low-confidence {lo['win_rate_pct']}% win rate."
            )

    weak = [k for k, v in by_signal.items() if v["low_sample"]]
    if weak:
        notes.append(
            f"Low sample (<{min_sample}) for signal bucket(s): {', '.join(sorted(weak))} "
            "— treat those win rates as indicative only."
        )
    return notes


def get_performance_analytics(
    symbol: str | None = None,
    days: int = 365,
    min_sample: int = _MIN_SAMPLE,
) -> dict:
    """Realized-outcome analytics over CLOSED trades — does the model have edge?

    Buckets closed trades by signal, regime, and entry-confidence band, and
    reports win rate / avg P&L / total P&L per bucket plus a profit factor.
    Buckets below `min_sample` trades are flagged `low_sample` (win rate is noise).
    Confidence is read from each trade's analysis_snapshot.confidence.
    """
    try:
        cutoff = (date.today() - timedelta(days=max(days, 0))).isoformat()
        params: list = []
        uf = _user_filter(params)
        params.append(cutoff)
        conditions = [uf, "status = 'CLOSED'", "entry_date >= ?"]
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol.upper().strip())
        where = " AND ".join(conditions)

        conn = _db._get_connection()
        rows = conn.execute(
            f"SELECT * FROM trades WHERE {where} ORDER BY entry_date DESC",
            params,
        ).fetchall()
        closed = [_row_to_dict(r) for r in rows]

        overall = _bucket_stats(closed, min_sample)
        overall["profit_factor"] = _profit_factor(closed)

        by_signal = _group_stats(closed, lambda t: t.get("signal") or "unknown", min_sample)
        by_regime = _group_stats(closed, lambda t: t.get("regime") or "unknown", min_sample)
        by_conf = _group_stats(closed, lambda t: _confidence_band(_confidence_of(t)), min_sample)

        return {
            "filters": {
                "symbol": symbol.upper().strip() if symbol else None,
                "days": days,
                "min_sample": min_sample,
            },
            "closed_trades": len(closed),
            "overall": overall,
            "by_signal": by_signal,
            "by_regime": by_regime,
            "by_confidence_band": by_conf,
            "notes": _edge_notes(closed, by_signal, by_conf, min_sample),
        }
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
        params: list = []
        uf = _user_filter(params)
        params.append(cutoff)
        conditions = [uf, "entry_date >= ?"]

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
