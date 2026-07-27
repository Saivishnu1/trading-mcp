from __future__ import annotations

import math
import threading
import time

from datetime import date

from src.technical import indicators
from src.tools.technicals import _load_candles


def _error(symbol: str, message: str) -> dict:
    return {"symbol": symbol.upper(), "error": message}


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _is_invalid(v: object) -> bool:
    """Return True for None and for float NaN (which bypasses None-membership tests)."""
    return v is None or (isinstance(v, float) and math.isnan(v))


# System-wide confidence ceiling. Confidence is reported on a single 0–85 scale
# everywhere (regime detection AND trade setup) — no indicator model warrants
# 100% certainty. Internal scores are computed 0–100 then mapped into this band,
# preserving ordering and resolution rather than clamping a flat top at 85.
MAX_CONFIDENCE = 85

# RSI points either side of the 30/70 extremes within which the classification
# is flagged as unstable (the bins around these carry the largest scoring swing).
_RSI_BOUNDARY_TOL = 2


def _scale_confidence(raw_0_to_100: int) -> int:
    """Map a 0–100 internal score onto the system-wide 0–85 confidence band."""
    return min(MAX_CONFIDENCE, round(raw_0_to_100 * MAX_CONFIDENCE / 100))


# Canonical set of regime names emitted by detect_market_regime. This is the
# single source of truth — consumers that map regimes (e.g. intelligence/risk.py
# _REGIME_SCORES) are guarded against drift by a test asserting full coverage.
REGIMES: frozenset[str] = frozenset({
    "BULL_TREND",
    "BEAR_TREND",
    "BREAKOUT_POTENTIAL",
    "RANGE_BOUND",
    "NEUTRAL_BULLISH",
    "NEUTRAL_BEARISH",
})


def _validate_number(name: str, value: float) -> str | None:
    if value is None:
        return f"{name} is required"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number"
    if math.isnan(numeric):
        return f"{name} must be a valid number"
    if numeric <= 0:
        return f"{name} must be greater than zero"
    return None


# Lookback days and yfinance interval strings per timeframe.
# Weekly needs ~85 bars (600d/7) for EMA50 warmup; monthly needs ~83 bars (2500d/30).
_TIMEFRAME_LOOKBACK: dict[str, int] = {
    "daily":   150,
    "weekly":  600,
    "monthly": 2500,
}
_TIMEFRAME_INTERVAL: dict[str, str] = {
    "daily":   "1d",
    "weekly":  "1wk",
    "monthly": "1mo",
}

# Regime direction groupings for timeframe alignment logic.
_BULLISH_REGIMES: frozenset[str] = frozenset({"BULL_TREND", "NEUTRAL_BULLISH", "BREAKOUT_POTENTIAL"})
_BEARISH_REGIMES: frozenset[str] = frozenset({"BEAR_TREND", "NEUTRAL_BEARISH"})

# Short-TTL cache. A single recommend_trade / review_trade flow calls
# _analyze_technicals many times for the same symbol (setup → regime → strategy
# → plan). Caching collapses those into one fetch and guarantees every layer in
# the flow sees the *same* candle snapshot (no mid-call divergence).
_ANALYSIS_TTL = 60  # seconds
_ANALYSIS_CACHE: dict[tuple[str, int, str], tuple[dict, float]] = {}
_ANALYSIS_LOCK = threading.Lock()


def clear_analysis_cache() -> None:
    """Clear the technicals cache (manual refresh / test isolation seam)."""
    with _ANALYSIS_LOCK:
        _ANALYSIS_CACHE.clear()


def _analyze_technicals(symbol: str, lookback_days: int = 150, interval: str = "daily") -> dict:
    """Reuse the same historical loader and indicator math as technical tools.

    Cached for _ANALYSIS_TTL seconds per (symbol, lookback, interval) so a single
    recommendation/review flow fetches once and stays internally consistent.
    interval: friendly name — 'daily', 'weekly', or 'monthly'.
    """
    yf_interval = _TIMEFRAME_INTERVAL.get(interval, "1d")
    cache_key = (symbol.upper(), lookback_days, interval)
    with _ANALYSIS_LOCK:
        hit = _ANALYSIS_CACHE.get(cache_key)
        if hit is not None and time.monotonic() - hit[1] < _ANALYSIS_TTL:
            return hit[0]

    candles = _load_candles(symbol, lookback_days, interval=yf_interval)
    if not candles:
        result = _error(
            symbol,
            "no price data available — the data source may be temporarily "
            "unavailable or rate-limited; retry shortly, or verify the symbol "
            "if this persists",
        )
        with _ANALYSIS_LOCK:
            _ANALYSIS_CACHE[cache_key] = (result, time.monotonic())
        return result

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    last_close = round(closes[-1], 4)
    result = {
        "symbol": symbol.upper(),
        "last_close": last_close,
        "candles_used": len(closes),
        # Data provenance — analysis is built on yfinance end-of-day, split/
        # dividend-adjusted candles. last_candle_date enables staleness checks.
        "data_source": "yfinance_eod_adjusted",
        "last_candle_date": candles[-1].get("date"),
        "rsi_14": indicators.rsi(closes, 14),
        "ema_20": indicators.ema(closes, 20),
        "ema_50": indicators.ema(closes, 50),
        "macd": indicators.macd(closes),
        "adx_14": indicators.adx(highs, lows, closes, 14),
        "atr_14": indicators.atr(highs, lows, closes, 14),
    }
    with _ANALYSIS_LOCK:
        _ANALYSIS_CACHE[cache_key] = (result, time.monotonic())
    return result


def _staleness_days(last_candle_date: str | None) -> int | None:
    """Calendar days between the last candle and today, or None if unknown."""
    if not last_candle_date:
        return None
    try:
        d = date.fromisoformat(str(last_candle_date)[:10])
    except ValueError:
        return None
    return (date.today() - d).days


def _data_basis(technicals: dict) -> dict:
    """Provenance descriptor surfaced to callers (source + staleness)."""
    last_candle_date = technicals.get("last_candle_date")
    return {
        "source": technicals.get("data_source", "yfinance_eod_adjusted"),
        "candles_used": technicals.get("candles_used"),
        "last_candle_date": last_candle_date,
        "staleness_days": _staleness_days(last_candle_date),
    }


def _classify_regime(symbol: str, technicals: dict) -> dict:
    """Classify market regime from a technicals snapshot (any timeframe).

    Pure function — no I/O. Called by detect_market_regime (daily) and
    _regime_for_timeframe (weekly/monthly) so the classification rules are
    defined once and used identically across all timeframes.
    """
    if "error" in technicals:
        return technicals

    price = technicals["last_close"]
    rsi = technicals["rsi_14"]
    ema20 = technicals["ema_20"]
    ema50 = technicals["ema_50"]
    adx = technicals["adx_14"]["adx"]
    atr = technicals["atr_14"]

    if any(_is_invalid(x) for x in (price, rsi, ema20, ema50, adx, atr)):
        return _error(symbol, "insufficient data for regime detection")

    regime = "RANGE_BOUND"
    confidence = 55

    if ema20 > ema50 and adx > 25:
        regime = "BULL_TREND"
        confidence = min(100, int(70 + min(adx - 25, 15) + min(max(rsi - 55, 0), 15)))
    elif ema20 < ema50 and adx > 25:
        regime = "BEAR_TREND"
        confidence = min(100, int(70 + min(adx - 25, 15) + min(max(45 - rsi, 0), 15)))
    elif 20 <= adx <= 25 and rsi > 55 and price > ema20:
        regime = "BREAKOUT_POTENTIAL"
        confidence = min(100, int(60 + min((adx - 20) * 4, 20) + min(rsi - 55, 20)))
    elif adx < 20:
        regime = "RANGE_BOUND"
        confidence = min(100, int(65 + min(20 - adx, 15)))
    elif price > ema20 and price > ema50 and rsi > 55 and adx < 25:
        regime = "NEUTRAL_BULLISH"
        confidence = min(100, int(60 + min(rsi - 55, 15) + min(max(adx - 15, 0), 10)))
    elif price < ema20 and price < ema50 and rsi < 45 and adx < 25:
        regime = "NEUTRAL_BEARISH"
        confidence = min(100, int(60 + min(45 - rsi, 15) + min(max(adx - 15, 0), 10)))
    elif price >= ema20:
        regime = "NEUTRAL_BULLISH"
        confidence = 52
    else:
        regime = "NEUTRAL_BEARISH"
        confidence = 52

    return {
        "symbol": symbol.upper(),
        "regime": regime,
        "confidence": _scale_confidence(confidence),
        "price": price,
        "rsi": rsi,
        "ema20": ema20,
        "ema50": ema50,
        "adx": adx,
        "atr": atr,
    }


def detect_market_regime(symbol: str) -> dict:
    technicals = _analyze_technicals(symbol)
    return _classify_regime(symbol, technicals)


# ---------------------------------------------------------------------------
# Multi-timeframe alignment (Phase 19)
# ---------------------------------------------------------------------------

def _regime_direction(regime: str | None) -> str:
    """Map a regime name to its broad directional bias."""
    if regime in _BULLISH_REGIMES:
        return "bullish"
    if regime in _BEARISH_REGIMES:
        return "bearish"
    return "neutral"


def _alignment_level(daily_dir: str, weekly_dir: str, monthly_dir: str) -> str:
    """Classify the agreement across three timeframe directions."""
    # Hard conflict: daily and weekly directly oppose each other (both non-neutral)
    if daily_dir != "neutral" and weekly_dir != "neutral" and daily_dir != weekly_dir:
        return "CONFLICT"
    dirs = [daily_dir, weekly_dir, monthly_dir]
    if len(set(dirs)) == 1:
        return "STRONG"
    if dirs.count(daily_dir) >= 2 or dirs.count(weekly_dir) >= 2:
        return "PARTIAL"
    return "MIXED"


def _alignment_summary(daily: dict, weekly: dict, monthly: dict, alignment: str) -> str:
    d_reg = daily.get("regime") or "unknown"
    w_reg = weekly.get("regime") or "unknown"
    m_reg = monthly.get("regime") or "unknown"
    if alignment == "STRONG":
        d_dir = _regime_direction(d_reg)
        return f"Daily, weekly, and monthly all {d_dir} ({d_reg}) — strong timeframe alignment"
    if alignment == "CONFLICT":
        return (
            f"Daily {d_reg} conflicts with weekly {w_reg} — "
            "counter-trend risk, wait for higher timeframe confirmation"
        )
    if alignment == "PARTIAL":
        return f"Daily {d_reg}, weekly {w_reg}, monthly {m_reg} — majority aligned"
    return f"Daily {d_reg}, weekly {w_reg}, monthly {m_reg} — mixed signals across timeframes"


def _regime_for_timeframe(symbol: str, timeframe: str) -> dict:
    """Fetch candles for the given timeframe, classify regime, return slim summary."""
    lookback = _TIMEFRAME_LOOKBACK.get(timeframe, 150)
    technicals = _analyze_technicals(symbol, lookback_days=lookback, interval=timeframe)
    if "error" in technicals:
        return {"regime": None, "confidence": None, "error": technicals["error"]}
    result = _classify_regime(symbol, technicals)
    if "error" in result:
        return {"regime": None, "confidence": None, "error": result["error"]}
    rsi_val = result["rsi"]
    adx_val = result["adx"]
    return {
        "regime": result["regime"],
        "confidence": result["confidence"],
        "rsi": round(float(rsi_val), 1) if rsi_val is not None else None,
        "adx": round(float(adx_val), 1) if adx_val is not None else None,
    }


def get_regime_alignment(symbol: str) -> dict:
    """Return daily, weekly, and monthly regime with alignment classification."""
    daily = _regime_for_timeframe(symbol, "daily")
    weekly = _regime_for_timeframe(symbol, "weekly")
    monthly = _regime_for_timeframe(symbol, "monthly")

    daily_dir = _regime_direction(daily.get("regime"))
    weekly_dir = _regime_direction(weekly.get("regime"))
    monthly_dir = _regime_direction(monthly.get("regime"))

    alignment = _alignment_level(daily_dir, weekly_dir, monthly_dir)

    return {
        "symbol": symbol.upper(),
        "daily": daily,
        "weekly": weekly,
        "monthly": monthly,
        "alignment": alignment,
        "summary": _alignment_summary(daily, weekly, monthly, alignment),
    }


def calculate_risk_reward(entry: float, stoploss: float, target: float) -> dict:
    for name, value in (("entry", entry), ("stoploss", stoploss), ("target", target)):
        error = _validate_number(name, value)
        if error:
            return {"error": error}

    entry = float(entry)
    stoploss = float(stoploss)
    target = float(target)
    risk = abs(entry - stoploss)
    reward = abs(target - entry)
    rr = round(reward / risk, 4) if risk else None

    return {
        "entry": _round(entry),
        "stoploss": _round(stoploss),
        "target": _round(target),
        "risk": _round(risk),
        "reward": _round(reward),
        "rr": rr,
    }


def calculate_position_size(
    capital: float,
    risk_percent: float,
    entry: float,
    stoploss: float,
) -> dict:
    for name, value in (
        ("capital", capital),
        ("risk_percent", risk_percent),
        ("entry", entry),
        ("stoploss", stoploss),
    ):
        error = _validate_number(name, value)
        if error:
            return {"error": error}

    capital = float(capital)
    risk_percent = float(risk_percent)
    entry = float(entry)
    stoploss = float(stoploss)

    stop_distance = abs(entry - stoploss)
    risk_amount = capital * (risk_percent / 100.0)
    position_size = round(risk_amount / stop_distance, 4) if stop_distance else None

    result: dict = {
        "capital": _round(capital),
        "risk_percent": _round(risk_percent, 2),
        "risk_amount": _round(risk_amount),
        "position_size": position_size,
    }

    if position_size is not None and entry > 0:
        capital_required = position_size * entry
        if capital_required > capital:
            capped_size = math.floor(capital / entry) if entry > 0 else 0
            result["capital_ceiling_caution"] = (
                f"Risk-based position_size ({position_size}) would require "
                f"₹{_round(capital_required)} against ₹{_round(capital)} capital — "
                f"capped size at this entry/stoploss is {capped_size}"
            )
            result["capital_capped_position_size"] = capped_size
        result["capital_required"] = _round(capital_required)

    return result


def _score_setup(technicals: dict, regime_name: str) -> dict | None:
    """Pure scoring core shared by generate_trade_setup (daily-only, unchanged
    behavior) and generate_trade_setup_tf (Priority 1 — Timeframe Engine,
    any EXECUTION-role interval). Operates on any technicals dict with the
    same shape _analyze_technicals/get_technicals produce. Returns None when
    inputs are invalid (NaN/missing) — caller decides how to surface that.

    Extracted verbatim from generate_trade_setup's body — same math, same
    thresholds, same output keys — so daily-only callers see zero behavior
    change. Do not diverge the scoring rules between the two callers without
    updating both regression suites.
    """
    price = technicals["last_close"]
    rsi = technicals["rsi_14"]
    ema20 = technicals["ema_20"]
    ema50 = technicals["ema_50"]
    macd = technicals["macd"]
    adx = technicals["adx_14"]["adx"]
    atr = technicals["atr_14"]

    if any(_is_invalid(x) for x in (price, rsi, ema20, ema50, adx, atr, macd["macd"], macd["signal"])):
        return None

    bullish = 0
    bearish = 0
    # Priority 4 — Recommendation Evidence Engine. Each entry tags WHICH
    # indicator produced the line and its polarity (bullish/bearish/neutral)
    # at the moment it's known — inside the same if/elif that already
    # decides the score delta. generate_trade_setup's plain `reasoning`
    # list[str] (unchanged output contract) is derived from this below by
    # extracting just the text; nothing about the daily-only function's
    # output shape changes. generate_trade_setup_tf additionally surfaces
    # the tagged version as evidence_for/evidence_against.
    evidence: list[dict] = []

    def _log(indicator: str, polarity: str, points: int, text: str) -> None:
        evidence.append({"indicator": indicator, "polarity": polarity, "points": points, "text": text})

    if rsi > 70:
        bearish += 10
        _log("rsi", "bearish", 10, f"RSI at {rsi:.0f} is overbought — elevated mean-reversion risk.")
    elif rsi > 55:
        bullish += 20
        _log("rsi", "bullish", 20, f"RSI at {rsi:.0f} is above 55, favoring bullish momentum.")
    elif rsi < 30:
        bullish += 10
        _log("rsi", "bullish", 10, f"RSI at {rsi:.0f} is oversold — potential mean-reversion bounce.")
    elif rsi < 45:
        bearish += 20
        _log("rsi", "bearish", 20, f"RSI at {rsi:.0f} is below 45, favoring bearish momentum.")
    else:
        _log("rsi", "neutral", 0, f"RSI at {rsi:.0f} is neutral (45–55).")

    # Near-boundary caution: the 30/70 extremes carry the largest scoring swing,
    # so flag readings within a couple of points where the bin could flip.
    if abs(rsi - 70) <= _RSI_BOUNDARY_TOL or abs(rsi - 30) <= _RSI_BOUNDARY_TOL:
        _log("rsi", "neutral", 0,
             f"RSI {rsi:.0f} sits near an overbought/oversold boundary — "
             "the read may flip on a small move.")

    if price > ema20:
        bullish += 15
        _log("ema_20", "bullish", 15, "Price is trading above EMA20.")
    elif price < ema20:
        bearish += 15
        _log("ema_20", "bearish", 15, "Price is trading below EMA20.")

    if price > ema50:
        bullish += 15
        _log("ema_50", "bullish", 15, "Price is trading above EMA50.")
    elif price < ema50:
        bearish += 15
        _log("ema_50", "bearish", 15, "Price is trading below EMA50.")

    if macd["macd"] > macd["signal"]:
        bullish += 20
        _log("macd", "bullish", 20, "MACD is above the signal line, which is bullish.")
    elif macd["macd"] < macd["signal"]:
        bearish += 20
        _log("macd", "bearish", 20, "MACD is below the signal line, which is bearish.")

    if adx > 25:
        if bullish >= bearish:
            bullish += 20
            _log("adx", "bullish", 20, f"ADX at {adx} confirms stronger directional conviction.")
        else:
            bearish += 20
            _log("adx", "bearish", 20, f"ADX at {adx} confirms stronger directional conviction.")
    else:
        _log("adx", "neutral", 0, f"ADX at {adx} is <=25 — no directional conviction added.")

    if regime_name in {"BULL_TREND", "NEUTRAL_BULLISH"}:
        bullish += 10
        _log("regime", "bullish", 10, f"Market regime is {regime_name}, aligning with bullish setups.")
    elif regime_name in {"BEAR_TREND", "NEUTRAL_BEARISH"}:
        bearish += 10
        _log("regime", "bearish", 10, f"Market regime is {regime_name}, aligning with bearish setups.")
    elif regime_name == "BREAKOUT_POTENTIAL":
        bullish += 5
        bearish += 5
        _log("regime", "neutral", 0, "Breakout potential is building, but direction still needs confirmation.")
    else:
        _log("regime", "neutral", 0, "Range-bound conditions reduce directional conviction.")

    if bullish >= 60 and bullish > bearish:
        signal = "BUY"
        confidence = bullish
    elif bearish >= 60 and bearish > bullish:
        signal = "SELL"
        confidence = bearish
    elif bullish > bearish:
        signal = "NEUTRAL_BULLISH"
        confidence = bullish
    elif bearish > bullish:
        signal = "NEUTRAL_BEARISH"
        confidence = bearish
    else:
        signal = "NEUTRAL"
        confidence = max(bullish, bearish)
        _log("composite", "neutral", 0, "Bullish and bearish evidence is balanced.")

    reasoning: list[str] = [e["text"] for e in evidence]

    # Regime-aware target multipliers (from entry, measured from price).
    # Entry buffer: 0.25×ATR. Stop distance: 1.00×ATR.
    # risk = 1.25×ATR for all directional setups.
    # Target chosen so RR >= 1.2 in the weakest regime (RANGE_BOUND).
    _target_atr = {
        "BULL_TREND":         2.75,  # reward 2.50×ATR → RR 2.0
        "BEAR_TREND":         2.75,  # reward 2.50×ATR → RR 2.0
        "BREAKOUT_POTENTIAL": 2.75,  # reward 2.50×ATR → RR 2.0
        "NEUTRAL_BULLISH":    2.25,  # reward 2.00×ATR → RR 1.6
        "NEUTRAL_BEARISH":    2.25,  # reward 2.00×ATR → RR 1.6
        "RANGE_BOUND":        1.75,  # reward 1.50×ATR → RR 1.2
    }.get(regime_name, 2.25)

    entry_above = _round(price + (atr * 0.25))
    entry_below = _round(price - (atr * 0.25))
    bull_target = _round(price + (atr * _target_atr))
    bear_target = _round(price - (atr * _target_atr))

    # Legacy scalar fields — derived from zone fields so both schemas stay in sync.
    # BUY / NEUTRAL_BULLISH: enter on breakout above, target up, stop below.
    # SELL / NEUTRAL_BEARISH: enter on breakdown below, target down, stop above.
    # NEUTRAL: symmetric zone around price.
    if signal in {"BUY", "NEUTRAL_BULLISH"}:
        entry_scalar = entry_above
        stoploss_scalar = _round(price - (atr * 1.0))
        target_scalar = bull_target
    elif signal in {"SELL", "NEUTRAL_BEARISH"}:
        entry_scalar = entry_below
        stoploss_scalar = _round(price + (atr * 1.0))
        target_scalar = bear_target
    else:  # NEUTRAL
        entry_scalar = _round(price)
        stoploss_scalar = _round(price - atr)
        target_scalar = _round(price + atr)

    return {
        "signal": signal,
        "confidence": _scale_confidence(confidence),
        # Legacy scalar fields (backward-compatible with Dashboard / Journal / Alerts)
        "entry": entry_scalar,
        "stoploss": stoploss_scalar,
        "target": target_scalar,
        # Zone fields (new schema)
        "entry_above": entry_above,
        "entry_below": entry_below,
        "bull_target": bull_target,
        "bear_target": bear_target,
        "reasoning": reasoning,
        "_evidence": evidence,  # tagged version, private — see build_evidence() for the public shape
    }


def generate_trade_setup(symbol: str) -> dict:
    technicals = _analyze_technicals(symbol)
    if "error" in technicals:
        return technicals

    regime = detect_market_regime(symbol)
    if "error" in regime:
        return regime

    scored = _score_setup(technicals, regime["regime"])
    if scored is None:
        return _error(symbol, "insufficient data for trade setup")
    scored = {k: v for k, v in scored.items() if k != "_evidence"}

    return {
        "symbol": symbol.upper(),
        **scored,
        "data_basis": _data_basis(technicals),
    }


def generate_trade_setup_tf(symbol: str, horizon: str, interval: str) -> dict:
    """Priority 1 — Timeframe Engine consumer. Same scoring core as
    generate_trade_setup (see _score_setup), but the technicals come from
    src.timeframe.engine.get_technicals(), which refuses the call outright
    if (horizon, interval) has no defined role at all, and tags the result
    with which role this interval plays — so a caller cannot mistake a
    CONTEXT-role read for one that's allowed to gate an entry.

    Parallel to generate_trade_setup, not a replacement — existing callers
    (create_trade_plan, recommend_trade, build_option_strategy, review_trade)
    are unchanged and keep calling the daily-only function. This is the
    entry point for any NEW recommendation path that wants explicit
    timeframe validation instead of an implicit daily default.

    horizon: one of src.timeframe.policy.HoldingHorizon's values, e.g.
        "INTRADAY_OPTIONS", "SWING", "POSITIONAL".
    interval: e.g. "15minute", "day", "week" — must have a role under the
        given horizon per src.timeframe.policy.POLICY, or this refuses.
    """
    from src.timeframe.confidence import adjust_confidence
    from src.timeframe.engine import get_technicals
    from src.timeframe.evidence import build_context_summary, build_evidence
    from src.timeframe.policy import HoldingHorizon, context_intervals
    from src.timeframe.thesis import build_trade_thesis
    from src.timeframe.trace import build_decision_trace

    try:
        horizon_enum = HoldingHorizon(horizon)
    except ValueError:
        return _error(symbol, f"unknown horizon {horizon!r} — see src.timeframe.policy.HoldingHorizon")

    technicals = get_technicals(symbol, horizon_enum, interval)
    if "error" in technicals:
        return technicals

    if not technicals.get("can_gate_entry"):
        return {
            "symbol": symbol.upper() if isinstance(symbol, str) else symbol,
            "error": (
                f"interval={interval!r} is role={technicals.get('role')} under "
                f"horizon={horizon!r} — CONTEXT/DISALLOWED intervals cannot "
                "produce an entry trade setup by themselves. Call with an "
                "EXECUTION or FINE_ENTRY interval for this horizon, or use "
                "the CONTEXT read only to inform confidence/sizing on an "
                "EXECUTION-role setup."
            ),
            "horizon": horizon,
            "interval": interval,
            "role": technicals.get("role"),
        }

    # Regime classification needs to be computed from the SAME timeframe's
    # technicals — reusing detect_market_regime (always daily) here would
    # silently reintroduce exactly the timeframe-mixing bug this engine
    # exists to prevent.
    regime_dict = _classify_regime(symbol, technicals)

    scored = _score_setup(technicals, regime_dict["regime"])
    if scored is None:
        return _error(symbol, "insufficient data for trade setup")

    evidence_split = build_evidence(scored.pop("_evidence", []), scored["signal"])

    # Priority 4 — attempt one CONTEXT-role fetch for this horizon (e.g.
    # SWING's "week", INTRADAY_OPTIONS' "day") to populate context/rejected.
    # Best-effort: a context fetch failing (stale/unavailable) never blocks
    # the EXECUTION-role setup that already scored successfully above — it
    # only means context/rejected reflect that failure instead of a reading.
    context_technicals = None
    context_error = None
    ctx_intervals = context_intervals(horizon_enum)
    if ctx_intervals:
        ctx_result = get_technicals(symbol, horizon_enum, ctx_intervals[0])
        if "error" in ctx_result:
            context_error = ctx_result["error"]
        else:
            context_technicals = ctx_result
    context_split = build_context_summary(context_technicals, context_error)

    result = {
        "symbol": symbol.upper(),
        **scored,
        "horizon": horizon,
        "interval": interval,
        "role": technicals.get("role"),
        "data_basis": {
            "source": technicals.get("data_source"),
            "last_candle_date": technicals.get("last_candle_date"),
            "last_candle_datetime": technicals.get("last_candle_datetime"),
            "staleness_days": _staleness_days(technicals.get("last_candle_date")),
        },
        # Priority 2 — per-indicator metadata for every indicator that fed
        # this setup's score, so the setup is auditable back to individual
        # indicator freshness/source, not just the aggregate data_basis.
        "indicator_metadata": technicals.get("indicator_metadata", []),
        # Priority 4 — Recommendation Evidence Engine.
        "evidence_for": evidence_split["evidence_for"],
        "evidence_against": evidence_split["evidence_against"],
        "ignored": evidence_split["ignored"],
        "context": context_split["context"],
        "rejected": context_split["rejected"],
    }
    # Priority 6 — Trade Thesis Engine: "why this trade exists" (reframed
    # from evidence_for above) paired with "why it fails" (concrete,
    # checkable invalidation conditions from this SAME timeframe's technicals).
    result["thesis"] = build_trade_thesis(result, technicals)
    # Priority 5 — Decision Trace. Pure reformatting of everything already
    # in `result` above; adds no new data, just one coherent audit record.
    # Built BEFORE the confidence adjustment below because Priority 7's
    # penalties are themselves partly derived from this trace's own
    # data_quality/indicators_rejected verdicts.
    result["decision_trace"] = build_decision_trace(result)
    # Priority 7 — Confidence rework. Reduces (never increases) the raw
    # hand-weighted confidence when this SAME pipeline already found a real
    # problem: mixed-timeframe conflict, missing indicator data, internal
    # disagreement between evidence_for/evidence_against, or a DEGRADED
    # decision_trace verdict. The raw score is preserved for audit.
    conf_adjustment = adjust_confidence(result, result["decision_trace"])
    result["raw_confidence"] = conf_adjustment["raw_confidence"]
    result["confidence"] = conf_adjustment["adjusted_confidence"]
    result["confidence_penalties"] = conf_adjustment["penalties"]
    result["confidence_not_checked"] = conf_adjustment["not_checked"]
    # The trace's own `confidence` field must reflect what was actually
    # reported (the adjusted value), not the pre-penalty raw score it was
    # built from a moment ago — otherwise the audit record would contradict
    # the thing it's meant to be auditing.
    result["decision_trace"]["confidence"] = result["confidence"]
    return result


def recommend_strategy(symbol: str) -> dict:
    regime = detect_market_regime(symbol)
    if "error" in regime:
        return regime

    setup = generate_trade_setup(symbol)
    if "error" in setup:
        return setup

    regime_name = regime["regime"]
    rsi = regime["rsi"]
    adx = regime["adx"]
    signal = setup["signal"]

    secondary: str | None = None

    # Priority order: Signal > Regime > RSI > ADX
    # Conflict resolution: directional signal overrides range-bound regime.
    if signal == "BUY":
        if regime_name == "RANGE_BOUND":
            strategy = "Bull Call Spread"
            secondary = "Iron Condor"
            reason = (
                f"BUY signal (bullish score {setup['confidence']}) overrides range-bound conditions "
                f"(ADX {adx}). Bull Call Spread captures directional upside with defined risk; "
                "Iron Condor remains viable if price stays pinned."
            )
        elif regime_name == "BULL_TREND" and rsi >= 60:
            strategy = "Long Call"
            reason = f"Bull trend confirmed by ADX at {adx} with RSI at {rsi} supports a directional upside trade."
        else:
            strategy = "Bull Call Spread"
            reason = (
                f"BUY signal with {regime_name} regime — a defined-risk spread captures upside "
                f"while limiting premium outlay at ADX {adx}."
            )
    elif signal == "SELL":
        if regime_name == "RANGE_BOUND":
            strategy = "Bear Put Spread"
            secondary = "Iron Condor"
            reason = (
                f"SELL signal (bearish score {setup['confidence']}) overrides range-bound conditions "
                f"(ADX {adx}). Bear Put Spread captures directional downside with defined risk; "
                "Iron Condor remains viable if price stays pinned."
            )
        elif regime_name == "BEAR_TREND" and rsi <= 40:
            strategy = "Long Put"
            reason = f"Bear trend confirmed by ADX at {adx} with RSI at {rsi} supports a directional downside trade."
        else:
            strategy = "Bear Put Spread"
            reason = (
                f"SELL signal with {regime_name} regime — a defined-risk spread captures downside "
                f"while controlling premium outlay at ADX {adx}."
            )
    elif signal == "NEUTRAL_BULLISH":
        strategy = "Bull Call Spread"
        reason = (
            f"Mild bullish conviction ({regime_name}) favours a defined-risk spread over an outright long option."
        )
    elif signal == "NEUTRAL_BEARISH":
        strategy = "Bear Put Spread"
        reason = (
            f"Mild bearish conviction ({regime_name}) favours a defined-risk spread over an outright long put."
        )
    else:
        # NEUTRAL signal — regime drives the choice
        if regime_name == "RANGE_BOUND":
            strategy = "Iron Condor"
            reason = f"No directional conviction and ADX at {adx} confirms low trend strength — ideal for a range-selling structure."
        elif regime_name == "BREAKOUT_POTENTIAL":
            if adx >= 23:
                strategy = "Long Straddle"
                reason = "Trend strength is building with no clear direction — a long straddle captures the potential expansion."
            else:
                strategy = "Long Strangle"
                reason = "Breakout potential with lower ADX — a strangle reduces premium cost while waiting for direction."
        elif regime_name in ("BULL_TREND", "NEUTRAL_BULLISH"):
            strategy = "Bull Call Spread"
            reason = f"Regime is {regime_name} despite neutral signal — a mildly bullish spread is the lower-risk fit."
        elif regime_name in ("BEAR_TREND", "NEUTRAL_BEARISH"):
            strategy = "Bear Put Spread"
            reason = f"Regime is {regime_name} despite neutral signal — a mildly bearish spread is the lower-risk fit."
        else:
            strategy = "Iron Condor"
            reason = f"No clear directional bias — ADX at {adx} suggests range conditions are appropriate."

    return {
        "symbol": symbol.upper(),
        "regime": regime_name,
        "signal": signal,
        # "strategy" kept for dashboard backward compatibility (reads strat_result.get("strategy"))
        "strategy": strategy,
        "recommended": strategy,
        "secondary": secondary,
        "reason": reason,
    }
