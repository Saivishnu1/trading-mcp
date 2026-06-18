from __future__ import annotations

from datetime import date

from src.journal.service import get_open_trades as _get_open_trades
from src.planner.trade_plan import create_trade_plan as _create_trade_plan
from src.review.reviewer import review_trade as _review_trade
from src.catalyst.event_risk import get_event_risk as _get_event_risk
from src.intelligence.vix import get_india_vix as _get_india_vix
from src.intelligence.global_pulse import get_global_pulse as _get_global_pulse
from src.intelligence.events import get_upcoming_events as _get_upcoming_events
from src.intelligence.risk import get_market_risk_score as _get_market_risk_score

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LONG_SIGNALS: frozenset[str] = frozenset({"BUY", "NEUTRAL_BULLISH"})
_SHORT_SIGNALS: frozenset[str] = frozenset({"SELL", "NEUTRAL_BEARISH"})

_EVENT_RISK_BLOCK = 80
_EVENT_RISK_CAUTION = 60
_EVENT_RISK_SIZE_FACTOR = 0.70
_DUPLICATE_SIZE_FACTOR = 0.50


def _direction_from_signal(signal: str) -> str | None:
    if signal in _LONG_SIGNALS:
        return "LONG"
    if signal in _SHORT_SIGNALS:
        return "SHORT"
    return None


def _apply_size_factors(base_size: int | None, factors: list[float]) -> int | None:
    if base_size is None:
        return None
    result = float(base_size)
    for f in factors:
        result *= f
    return max(1, int(round(result)))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recommend_trade(
    symbol: str,
    capital: float = 100_000,
    risk_percent: float = 1.0,
) -> dict:
    try:
        symbol = symbol.upper().strip()

        # 1. Existing exposure
        open_result = _get_open_trades(symbol)
        existing_open: list[dict] = open_result.get("trades", []) if "error" not in open_result else []

        # 2. Trade plan — regime, signal, entry, sizing
        plan = _create_trade_plan(symbol, capital=capital, risk_percent=risk_percent)
        if "error" in plan:
            return {"error": plan["error"], "symbol": symbol}

        signal: str = plan.get("signal", "NEUTRAL")
        trade_allowed: bool = plan.get("trade_allowed", False)
        direction = _direction_from_signal(signal)
        regime = plan.get("market_context", {}).get("regime")
        entry = plan.get("entry")
        stoploss = plan.get("stoploss")
        target = plan.get("target")
        rr_val = plan.get("risk_reward", {}).get("rr")
        base_position_size = plan.get("position", {}).get("position_size")
        strategy = plan.get("strategy", {}).get("recommended")
        trade_quality = plan.get("trade_quality")

        # 3. Event risk
        event_risk_score: int | None = None
        event_risk_rating: str | None = None
        _event_risk_available = False
        try:
            er = _get_event_risk(symbol)
            if "error" not in er:
                event_risk_score = er.get("event_risk_score")
                event_risk_rating = er.get("event_risk_rating")
                _event_risk_available = True
        except Exception:
            pass

        # 4. VIX context
        vix: float | None = None
        vix_caution: str | None = None
        _vix_available = False
        try:
            vix_data = _get_india_vix()
            if "error" not in vix_data:
                vix = vix_data.get("vix")
                vix_caution = vix_data.get("caution_level")
                _vix_available = True
        except Exception:
            pass

        # 5. Apply gating and adjustments
        cautions: list[str] = []
        risk_adjustments: list[str] = []
        size_factors: list[float] = []

        if not _event_risk_available:
            cautions.append("Event risk data unavailable — gating skipped, verify manually")
        if not _vix_available:
            cautions.append("VIX data unavailable — volatility gating skipped, verify manually")

        # Event risk gating
        if event_risk_score is not None:
            if event_risk_score >= _EVENT_RISK_BLOCK:
                trade_allowed = False
                cautions.append(
                    f"Event risk is EXTREME ({event_risk_score}/100) — major catalyst imminent"
                )
            elif event_risk_score >= _EVENT_RISK_CAUTION:
                cautions.append(
                    f"Event risk is HIGH ({event_risk_score}/100) — consider reducing size"
                )
                size_factors.append(_EVENT_RISK_SIZE_FACTOR)
                risk_adjustments.append("Position size reduced 30% due to HIGH event risk")

        # VIX gating
        if vix_caution == "EXTREME":
            trade_allowed = False
            cautions.append("India VIX is EXTREME — market panic, avoid new positions")
        elif vix_caution == "HIGH":
            cautions.append("India VIX is HIGH — elevated volatility, trade with caution")

        # Duplicate exposure
        same_dir_open = [t for t in existing_open if t.get("direction") == direction] if direction else []
        duplicate_exposure = len(same_dir_open) > 0
        if duplicate_exposure:
            cautions.append(
                f"Already have {len(same_dir_open)} open {direction} trade(s) on {symbol}"
            )
            size_factors.append(_DUPLICATE_SIZE_FACTOR)
            risk_adjustments.append("Position size reduced 50% due to duplicate exposure")

        # Final position size
        position_size = _apply_size_factors(base_position_size, size_factors)

        # 6. Final recommendation
        if not trade_allowed:
            recommendation = "AVOID"
        elif cautions:
            recommendation = "WAIT"
        else:
            recommendation = "ENTER"

        # 7. Reasons
        reasons: list[str] = []
        if direction:
            reasons.append(f"{regime or 'Unknown'} regime with {signal} signal")
        if event_risk_score is not None:
            reasons.append(f"Event risk {event_risk_rating or ''} ({event_risk_score}/100)".strip())
        if vix_caution:
            reasons.append(f"VIX caution level: {vix_caution}")

        return {
            "symbol": symbol,
            "recommendation": recommendation,
            "trade_allowed": trade_allowed,
            "direction": direction,
            "regime": regime,
            "signal": signal,
            "entry": entry,
            "stoploss": stoploss,
            "target": target,
            "risk_reward": rr_val,
            "position_size": position_size,
            "strategy": strategy,
            "trade_quality": trade_quality,
            "event_risk_score": event_risk_score,
            "event_risk_rating": event_risk_rating,
            "vix": vix,
            "vix_caution": vix_caution,
            "duplicate_exposure": duplicate_exposure,
            "existing_open_trades": [
                {
                    "trade_id": t["trade_id"],
                    "direction": t["direction"],
                    "entry_price": t["entry_price"],
                }
                for t in existing_open
            ],
            "cautions": cautions,
            "reasons": reasons,
            "risk_adjustments": risk_adjustments,
            "gating_data_available": {
                "event_risk": _event_risk_available,
                "vix": _vix_available,
            },
        }
    except Exception as exc:
        return {"error": str(exc), "symbol": symbol if isinstance(symbol, str) else "unknown"}


def review_open_trades() -> dict:
    try:
        open_result = _get_open_trades()
        if "error" in open_result:
            return {"error": open_result["error"]}

        trades = open_result.get("trades", [])
        positions: list[dict] = []
        needs_attention = 0
        total_unrealised_pnl = 0.0
        at_risk_count = 0
        action_counts: dict[str, int] = {"HOLD": 0, "REDUCE": 0, "EXIT": 0}

        for trade in trades:
            base = {
                "trade_id": trade["trade_id"],
                "symbol": trade["symbol"],
                "direction": trade["direction"],
                "entry_price": trade["entry_price"],
                "quantity": trade.get("quantity"),
                "stoploss": trade.get("stoploss"),
                "target": trade.get("target"),
                "entry_date": trade["entry_date"],
                "strategy": trade.get("strategy"),
            }

            try:
                entry_d = date.fromisoformat(trade["entry_date"])
                days_held = (date.today() - entry_d).days

                review = _review_trade(
                    symbol=trade["symbol"],
                    direction=trade["direction"],
                    entry_price=trade["entry_price"],
                    holding_days=days_held,
                )

                action = review.get("action", "HOLD")
                current_price = review.get("current_price")
                pnl_pct = review.get("current_pnl_percent")

                # Current P&L (absolute)
                qty = trade.get("quantity") or 1
                if current_price is not None:
                    ep = trade["entry_price"]
                    if trade["direction"] == "LONG":
                        current_pnl = round((current_price - ep) * qty, 2)
                    else:
                        current_pnl = round((ep - current_price) * qty, 2)
                    total_unrealised_pnl += current_pnl
                else:
                    current_pnl = None

                # Breach checks
                stoploss = trade.get("stoploss")
                tgt = trade.get("target")
                stoploss_breached = False
                target_reached = False

                if current_price is not None:
                    if trade["direction"] == "LONG":
                        stoploss_breached = bool(stoploss and current_price <= stoploss)
                        target_reached = bool(tgt and current_price >= tgt)
                    else:
                        stoploss_breached = bool(stoploss and current_price >= stoploss)
                        target_reached = bool(tgt and current_price <= tgt)

                if stoploss_breached:
                    at_risk_count += 1
                if action in ("EXIT", "REDUCE"):
                    needs_attention += 1
                action_counts[action] = action_counts.get(action, 0) + 1

                base.update({
                    "current_price": current_price,
                    "current_pnl": current_pnl,
                    "current_pnl_percent": pnl_pct,
                    "days_held": days_held,
                    "action": action,
                    "thesis_status": review.get("thesis_status"),
                    "current_regime": review.get("current_regime"),
                    "current_signal": review.get("current_signal"),
                    "stoploss_breached": stoploss_breached,
                    "target_reached": target_reached,
                    "error": None,
                })
            except Exception as exc:
                base.update({
                    "current_price": None,
                    "current_pnl": None,
                    "current_pnl_percent": None,
                    "days_held": None,
                    "action": None,
                    "thesis_status": None,
                    "current_regime": None,
                    "current_signal": None,
                    "stoploss_breached": None,
                    "target_reached": None,
                    "error": str(exc),
                })

            positions.append(base)

        return {
            "count": len(positions),
            "needs_attention": needs_attention,
            "positions": positions,
            "summary": {
                "total_open": len(positions),
                "hold": action_counts.get("HOLD", 0),
                "reduce": action_counts.get("REDUCE", 0),
                "exit": action_counts.get("EXIT", 0),
                "total_unrealised_pnl": round(total_unrealised_pnl, 2),
                "at_risk_count": at_risk_count,
            },
        }
    except Exception as exc:
        return {"error": str(exc)}


def get_daily_brief() -> dict:
    try:
        today = date.today().isoformat()

        # Market context — each sub-call isolated
        market_context: dict = {}

        try:
            vix_data = _get_india_vix()
            market_context["vix"] = vix_data.get("vix")
            market_context["vix_caution"] = vix_data.get("caution_level")
        except Exception:
            market_context["vix"] = None
            market_context["vix_caution"] = None

        try:
            risk_data = _get_market_risk_score()
            market_context["overall_risk_score"] = risk_data.get("score")
            market_context["overall_risk_rating"] = risk_data.get("rating")
        except Exception:
            market_context["overall_risk_score"] = None
            market_context["overall_risk_rating"] = None

        try:
            pulse_data = _get_global_pulse()
            market_context["global_sentiment"] = pulse_data.get("overall_sentiment")
        except Exception:
            market_context["global_sentiment"] = None

        try:
            events_data = _get_upcoming_events(days_ahead=3)
            market_context["upcoming_events"] = events_data.get("events", [])
        except Exception:
            market_context["upcoming_events"] = []

        # Open positions
        open_positions = review_open_trades()

        # Alerts
        alerts: list[str] = []
        if "positions" in open_positions:
            for pos in open_positions["positions"]:
                if pos.get("action") == "EXIT":
                    alerts.append(
                        f"{pos['trade_id']} {pos['symbol']} {pos['direction']}: "
                        f"EXIT — {pos.get('thesis_status', 'thesis invalidated')}"
                    )
                if pos.get("stoploss_breached"):
                    alerts.append(
                        f"{pos['trade_id']} {pos['symbol']}: "
                        f"STOPLOSS BREACHED at {pos.get('current_price')}"
                    )

        for event in market_context.get("upcoming_events", []):
            if event.get("impact") == "HIGH":
                alerts.append(
                    f"High-impact event in {event.get('days_until', '?')} day(s): "
                    f"{event.get('name', 'Unknown')}"
                )

        # Summary
        parts: list[str] = []
        risk_score = market_context.get("overall_risk_score")
        risk_rating = market_context.get("overall_risk_rating")
        if risk_score is not None:
            parts.append(f"Market risk is {risk_rating} ({risk_score}/100).")

        vix_caution = market_context.get("vix_caution")
        if vix_caution:
            parts.append(f"VIX caution: {vix_caution}.")

        global_sentiment = market_context.get("global_sentiment")
        if global_sentiment:
            parts.append(f"Global sentiment: {global_sentiment}.")

        if "error" not in open_positions:
            s = open_positions.get("summary", {})
            n = open_positions.get("count", 0)
            parts.append(
                f"You have {n} open position(s): "
                f"{s.get('hold', 0)} HOLD, "
                f"{s.get('reduce', 0)} REDUCE, "
                f"{s.get('exit', 0)} EXIT."
            )

        if alerts:
            parts.append(f"{len(alerts)} alert(s) need attention.")

        return {
            "date": today,
            "market_context": market_context,
            "open_positions": open_positions,
            "alerts": alerts,
            "summary": " ".join(parts) if parts else "No market data available.",
        }
    except Exception as exc:
        return {"error": str(exc)}
