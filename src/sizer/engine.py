from __future__ import annotations

import math

from src.common.scoring import apply_size_factors as _apply_size_factors
from src.journal.service import get_open_trades as _get_open_trades
from src.portfolio_intelligence.service import (
    get_portfolio_risk_report as _get_portfolio_risk_report,
)
from src.recommendations.engine import recommend_trade as _recommend_trade

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ELEVATED_THRESHOLD = 7.0     # portfolio heat % → reduce 25%
_CRITICAL_THRESHOLD = 9.0     # portfolio heat % → reduce 50%
_ELEVATED_FACTOR = 0.75
_CRITICAL_FACTOR = 0.50

_PORT_RISK_HIGH_SCORE = 75
_PORT_RISK_EXTREME_SCORE = 90
_PORT_RISK_HIGH_FACTOR = 0.75
_PORT_RISK_EXTREME_FACTOR = 0.50

_DEFAULT_RISK_PCT = 0.02       # 2% assumed risk per position when stoploss absent
_OPTIONS_CAUTION_THRESHOLD = 5.0  # capital_at_risk_pct above which a caution is added


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _compute_portfolio_heat(capital: float) -> tuple[float, list[str]]:
    """Return (heat_pct, caution_messages). Never raises."""
    cautions: list[str] = []
    try:
        result = _get_open_trades()
        if "error" in result:
            cautions.append(f"Portfolio heat unavailable: {result['error']}")
            return 0.0, cautions
        trades = result.get("trades", [])
        heat_amount = 0.0
        for t in trades:
            ep = t.get("entry_price") or 0.0
            sl = t.get("stoploss")
            qty = t.get("quantity") or 1
            direction = (t.get("direction") or "LONG").upper()
            if sl is not None and ep > 0:
                if direction == "LONG":
                    risk = max(0.0, (ep - sl) * qty)
                else:
                    risk = max(0.0, (sl - ep) * qty)
            else:
                risk = ep * qty * _DEFAULT_RISK_PCT
            heat_amount += risk
        heat_pct = round(heat_amount / capital * 100, 2) if capital > 0 else 0.0
        return heat_pct, cautions
    except Exception as exc:
        cautions.append(f"Portfolio heat unavailable: {exc}")
        return 0.0, cautions


def _get_portfolio_risk_adjustment() -> tuple[float, str | None, str]:
    """Return (size_factor, adjustment_msg_or_None, rating). Never raises."""
    try:
        report = _get_portfolio_risk_report()
        if "error" in report:
            return 1.0, None, "UNKNOWN"
        score = report.get("portfolio_risk_score") or 0
        rating = report.get("rating") or "UNKNOWN"
        if score >= _PORT_RISK_EXTREME_SCORE:
            return (
                _PORT_RISK_EXTREME_FACTOR,
                f"Portfolio risk EXTREME ({score}/100) — size halved",
                rating,
            )
        if score >= _PORT_RISK_HIGH_SCORE:
            return (
                _PORT_RISK_HIGH_FACTOR,
                f"Portfolio risk HIGH ({score}/100) — size reduced 25%",
                rating,
            )
        return 1.0, None, rating
    except Exception:
        return 1.0, None, "UNKNOWN"


def _heat_size_factor(heat_pct: float) -> tuple[float, str | None]:
    if heat_pct >= _CRITICAL_THRESHOLD:
        return _CRITICAL_FACTOR, f"Portfolio heat CRITICAL ({heat_pct}%) — size reduced 50%"
    if heat_pct >= _ELEVATED_THRESHOLD:
        return _ELEVATED_FACTOR, f"Portfolio heat ELEVATED ({heat_pct}%) — size reduced 25%"
    return 1.0, None


def _apply_capital_ceiling(
    units: int,
    unit_price: float,
    capital: float,
    unit_multiplier: int = 1,
) -> tuple[int, str | None]:
    """Clamp `units` so units * unit_price * unit_multiplier never exceeds `capital`.

    Risk-based sizing (risk_budget / stoploss_distance) has no upper bound tied to
    account size — a tight stoploss can size a notional position larger than the
    entire stated capital. This is the backstop: it never loosens a size the
    heat/portfolio-risk factors already reduced, only tightens further if the
    risk-based size still doesn't fit in the account.
    """
    if unit_price <= 0 or unit_multiplier <= 0 or capital <= 0:
        return units, None
    notional_per_unit = unit_price * unit_multiplier
    max_units = max(1, math.floor(capital / notional_per_unit))
    if units > max_units:
        return max_units, (
            f"Size clamped to capital ceiling: {units} would require "
            f"₹{round(units * notional_per_unit, 2)} against ₹{round(capital, 2)} "
            f"capital — reduced to {max_units}"
        )
    return units, None


def _build_equity_log_params(
    symbol: str,
    direction: str,
    entry: float,
    stoploss: float,
    quantity: int,
    max_loss: float,
    capital_at_risk_pct: float,
    portfolio_heat_pct: float,
    target: float | None,
    rr: float | None,
) -> dict:
    params: dict = {
        "symbol": symbol,
        "direction": direction,
        "entry_price": entry,
        "quantity": quantity,
        "stoploss": stoploss,
        "risk_amount": max_loss,
        "capital_at_risk": capital_at_risk_pct,
        "portfolio_heat_at_entry": portfolio_heat_pct,
    }
    if target is not None:
        params["target"] = target
    if rr is not None:
        params["risk_reward"] = rr
    return params


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def size_equity_trade(
    symbol: str,
    direction: str,
    entry: float,
    stoploss: float,
    capital: float = 100_000,
    risk_percent: float = 1.0,
    target: float | None = None,
) -> dict:
    try:
        symbol = symbol.upper().strip()
        direction = direction.upper().strip()

        if direction not in ("LONG", "SHORT"):
            return {"error": "direction must be LONG or SHORT"}
        if entry <= 0:
            return {"error": "entry must be positive"}

        if direction == "LONG":
            if stoploss >= entry:
                return {"error": "stoploss must be below entry for LONG"}
            stoploss_distance = entry - stoploss
        else:
            if stoploss <= entry:
                return {"error": "stoploss must be above entry for SHORT"}
            stoploss_distance = stoploss - entry

        risk_budget = capital * risk_percent / 100
        base_quantity = max(1, math.floor(risk_budget / stoploss_distance))

        portfolio_heat_pct, heat_cautions = _compute_portfolio_heat(capital)
        port_factor, port_adj_msg, portfolio_risk_rating = _get_portfolio_risk_adjustment()
        heat_factor, heat_adj_msg = _heat_size_factor(portfolio_heat_pct)

        size_adjustments = [m for m in [heat_adj_msg, port_adj_msg] if m]
        size_factors = [f for f in [heat_factor, port_factor] if f < 1.0]
        quantity = _apply_size_factors(base_quantity, size_factors) if size_factors else base_quantity

        quantity, capital_ceiling_note = _apply_capital_ceiling(
            quantity, entry, capital, unit_multiplier=1,
        )
        if capital_ceiling_note:
            size_adjustments.append(capital_ceiling_note)

        max_loss = round(quantity * stoploss_distance, 2)
        capital_required = round(quantity * entry, 2)
        capital_at_risk_pct = round(max_loss / capital * 100, 4) if capital > 0 else 0.0
        portfolio_heat_after = round(portfolio_heat_pct + capital_at_risk_pct, 2)

        rr = None
        if target is not None:
            reward = (target - entry) if direction == "LONG" else (entry - target)
            if stoploss_distance > 0:
                rr = round(reward / stoploss_distance, 2)

        log_params = _build_equity_log_params(
            symbol, direction, entry, stoploss, quantity,
            max_loss, capital_at_risk_pct, portfolio_heat_pct, target, rr,
        )

        result: dict = {
            "symbol": symbol,
            "direction": direction,
            "entry": entry,
            "stoploss": stoploss,
            "target": target,
            "quantity": quantity,
            "capital_required": capital_required,
            "risk_amount": max_loss,
            "capital_at_risk_pct": capital_at_risk_pct,
            "max_loss": max_loss,
            "portfolio_heat_pct": portfolio_heat_pct,
            "portfolio_heat_after_pct": portfolio_heat_after,
            "portfolio_risk_rating": portfolio_risk_rating,
            "size_adjustments": size_adjustments,
            "cautions": list(heat_cautions),
            "method": "FIXED_RISK",
            "log_trade_params": log_params,
        }
        if rr is not None:
            result["risk_reward"] = rr

        return result
    except Exception as exc:
        return {"error": str(exc)}


def size_options_trade(
    symbol: str,
    direction: str,
    premium: float,
    stoploss_premium: float,
    lot_size: int,
    capital: float = 100_000,
    risk_percent: float = 1.0,
) -> dict:
    try:
        symbol = symbol.upper().strip()
        direction = direction.upper().strip()

        if direction not in ("LONG", "SHORT"):
            return {"error": "direction must be LONG or SHORT"}
        if premium <= 0:
            return {"error": "premium must be positive"}
        if lot_size <= 0:
            return {"error": "lot_size must be positive"}

        premium_distance = premium - stoploss_premium
        if premium_distance <= 0:
            return {
                "error": (
                    "stoploss_premium must be below premium for a long option "
                    "(premium_distance must be positive)"
                )
            }

        risk_budget = capital * risk_percent / 100
        lot_risk = premium_distance * lot_size
        base_lots = max(1, math.floor(risk_budget / lot_risk))

        portfolio_heat_pct, heat_cautions = _compute_portfolio_heat(capital)
        port_factor, port_adj_msg, portfolio_risk_rating = _get_portfolio_risk_adjustment()
        heat_factor, heat_adj_msg = _heat_size_factor(portfolio_heat_pct)

        size_adjustments = [m for m in [heat_adj_msg, port_adj_msg] if m]
        size_factors = [f for f in [heat_factor, port_factor] if f < 1.0]
        lots = _apply_size_factors(base_lots, size_factors) if size_factors else base_lots

        lots, capital_ceiling_note = _apply_capital_ceiling(
            lots, premium, capital, unit_multiplier=lot_size,
        )
        if capital_ceiling_note:
            size_adjustments.append(capital_ceiling_note)

        quantity = lots * lot_size
        capital_required = round(lots * lot_size * premium, 2)
        max_loss = round(lots * lot_size * premium_distance, 2)
        capital_at_risk_pct = round(max_loss / capital * 100, 4) if capital > 0 else 0.0
        portfolio_heat_after = round(portfolio_heat_pct + capital_at_risk_pct, 2)

        cautions = list(heat_cautions)
        if capital_at_risk_pct > _OPTIONS_CAUTION_THRESHOLD:
            cautions.append(
                f"capital_at_risk_pct ({capital_at_risk_pct}%) exceeds "
                f"{_OPTIONS_CAUTION_THRESHOLD}% single-trade threshold for options"
            )

        log_params: dict = {
            "symbol": symbol,
            "direction": direction,
            "entry_price": premium,
            "quantity": quantity,
            "stoploss": stoploss_premium,
            "trade_type": "OPTIONS",
            "risk_amount": max_loss,
            "capital_at_risk": capital_at_risk_pct,
            "portfolio_heat_at_entry": portfolio_heat_pct,
        }

        return {
            "symbol": symbol,
            "direction": direction,
            "premium": premium,
            "stoploss_premium": stoploss_premium,
            "lot_size": lot_size,
            "lots": lots,
            "quantity": quantity,
            "capital_required": capital_required,
            "risk_amount": max_loss,
            "capital_at_risk_pct": capital_at_risk_pct,
            "max_loss": max_loss,
            "portfolio_heat_pct": portfolio_heat_pct,
            "portfolio_heat_after_pct": portfolio_heat_after,
            "portfolio_risk_rating": portfolio_risk_rating,
            "size_adjustments": size_adjustments,
            "cautions": cautions,
            "method": "FIXED_RISK",
            "log_trade_params": log_params,
        }
    except Exception as exc:
        return {"error": str(exc)}


def size_from_recommendation(
    symbol: str,
    capital: float = 100_000,
    risk_percent: float = 1.0,
) -> dict:
    try:
        symbol = symbol.upper().strip()

        rec = _recommend_trade(symbol=symbol, capital=capital, risk_percent=risk_percent)
        if "error" in rec:
            return {"error": rec["error"], "symbol": symbol}

        recommendation = rec.get("recommendation")
        trade_allowed = rec.get("trade_allowed", False)
        direction = rec.get("direction")
        entry = rec.get("entry")
        stoploss = rec.get("stoploss")
        target = rec.get("target")
        rr = rec.get("risk_reward")
        base_position_size = rec.get("position_size")
        signal = rec.get("signal")
        regime = rec.get("regime")
        strategy = rec.get("strategy")
        trade_quality = rec.get("trade_quality")
        event_risk_score = rec.get("event_risk_score")
        event_risk_rating = rec.get("event_risk_rating")
        vix = rec.get("vix")
        vix_caution = rec.get("vix_caution")
        duplicate_exposure = rec.get("duplicate_exposure", False)
        rec_cautions = rec.get("cautions", [])
        reasons = rec.get("reasons", [])

        # Portfolio heat (computed for all cases — informational even on AVOID)
        portfolio_heat_pct, heat_cautions = _compute_portfolio_heat(capital)

        if not trade_allowed or recommendation in ("AVOID", "WAIT"):
            cautions = list(rec_cautions) + list(heat_cautions)
            cautions.append("Trade not recommended — no sizing produced")
            return {
                "symbol": symbol,
                "recommendation": recommendation,
                "trade_allowed": trade_allowed,
                "direction": direction,
                "signal": signal,
                "regime": regime,
                "entry": entry,
                "stoploss": stoploss,
                "target": target,
                "risk_reward": rr,
                "strategy": strategy,
                "trade_quality": trade_quality,
                "event_risk_score": event_risk_score,
                "event_risk_rating": event_risk_rating,
                "vix": vix,
                "vix_caution": vix_caution,
                "duplicate_exposure": duplicate_exposure,
                "reasons": reasons,
                "quantity": None,
                "capital_required": None,
                "risk_amount": None,
                "capital_at_risk_pct": None,
                "max_loss": None,
                "portfolio_heat_pct": portfolio_heat_pct,
                "portfolio_heat_after_pct": None,
                "portfolio_risk_rating": None,
                "size_adjustments": [],
                "cautions": cautions,
                "method": None,
                "log_trade_params": None,
            }

        # Portfolio risk rating adjustment
        port_factor, port_adj_msg, portfolio_risk_rating = _get_portfolio_risk_adjustment()
        heat_factor, heat_adj_msg = _heat_size_factor(portfolio_heat_pct)

        size_adjustments = [m for m in [heat_adj_msg, port_adj_msg] if m]
        size_factors = [f for f in [heat_factor, port_factor] if f < 1.0]
        quantity = _apply_size_factors(base_position_size, size_factors) if size_factors else (base_position_size or 1)

        if entry is not None and entry > 0 and quantity:
            quantity, capital_ceiling_note = _apply_capital_ceiling(quantity, entry, capital)
            if capital_ceiling_note:
                size_adjustments.append(capital_ceiling_note)

        # Compute absolute sizing
        max_loss: float | None = None
        capital_required: float | None = None
        capital_at_risk_pct: float | None = None
        portfolio_heat_after: float | None = None
        log_params: dict | None = None

        if entry is not None and stoploss is not None and direction in ("LONG", "SHORT"):
            if direction == "LONG":
                stoploss_distance = max(0.0, entry - stoploss)
            else:
                stoploss_distance = max(0.0, stoploss - entry)

            if stoploss_distance > 0 and quantity:
                max_loss = round(quantity * stoploss_distance, 2)
                capital_required = round(quantity * entry, 2)
                capital_at_risk_pct = round(max_loss / capital * 100, 4) if capital > 0 else 0.0
                portfolio_heat_after = round(portfolio_heat_pct + capital_at_risk_pct, 2)

                log_params = {
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": entry,
                    "quantity": quantity,
                    "stoploss": stoploss,
                    "risk_amount": max_loss,
                    "capital_at_risk": capital_at_risk_pct,
                    "portfolio_heat_at_entry": portfolio_heat_pct,
                }
                if target is not None:
                    log_params["target"] = target
                if rr is not None:
                    log_params["risk_reward"] = rr
                if signal:
                    log_params["signal"] = signal
                if regime:
                    log_params["regime"] = regime

        cautions = list(rec_cautions) + list(heat_cautions)

        return {
            "symbol": symbol,
            "recommendation": recommendation,
            "trade_allowed": trade_allowed,
            "direction": direction,
            "signal": signal,
            "regime": regime,
            "entry": entry,
            "stoploss": stoploss,
            "target": target,
            "risk_reward": rr,
            "strategy": strategy,
            "trade_quality": trade_quality,
            "event_risk_score": event_risk_score,
            "event_risk_rating": event_risk_rating,
            "vix": vix,
            "vix_caution": vix_caution,
            "duplicate_exposure": duplicate_exposure,
            "quantity": quantity,
            "capital_required": capital_required,
            "risk_amount": max_loss,
            "capital_at_risk_pct": capital_at_risk_pct,
            "max_loss": max_loss,
            "portfolio_heat_pct": portfolio_heat_pct,
            "portfolio_heat_after_pct": portfolio_heat_after,
            "portfolio_risk_rating": portfolio_risk_rating,
            "size_adjustments": size_adjustments,
            "cautions": cautions,
            "method": "FIXED_RISK",
            "log_trade_params": log_params,
        }
    except Exception as exc:
        return {"error": str(exc), "symbol": symbol if isinstance(symbol, str) else "unknown"}
