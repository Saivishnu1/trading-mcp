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

    return {
        "capital": _round(capital),
        "risk_percent": _round(risk_percent, 2),
        "risk_amount": _round(risk_amount),
        "position_size": position_size,
    }


def generate_trade_setup(symbol: str) -> dict:
    technicals = _analyze_technicals(symbol)
    if "error" in technicals:
        return technicals

    regime = detect_market_regime(symbol)
    if "error" in regime:
        return regime

    price = technicals["last_close"]
    rsi = technicals["rsi_14"]
    ema20 = technicals["ema_20"]
    ema50 = technicals["ema_50"]
    macd = technicals["macd"]
    adx = technicals["adx_14"]["adx"]
    atr = technicals["atr_14"]

    if any(_is_invalid(x) for x in (price, rsi, ema20, ema50, adx, atr, macd["macd"], macd["signal"])):
        return _error(symbol, "insufficient data for trade setup")

    bullish = 0
    bearish = 0
    reasoning: list[str] = []

    if rsi > 70:
        bearish += 10
        reasoning.append(f"RSI at {rsi:.0f} is overbought — elevated mean-reversion risk.")
    elif rsi > 55:
        bullish += 20
        reasoning.append(f"RSI at {rsi:.0f} is above 55, favoring bullish momentum.")
    elif rsi < 30:
        bullish += 10
        reasoning.append(f"RSI at {rsi:.0f} is oversold — potential mean-reversion bounce.")
    elif rsi < 45:
        bearish += 20
        reasoning.append(f"RSI at {rsi:.0f} is below 45, favoring bearish momentum.")
    else:
        reasoning.append(f"RSI at {rsi:.0f} is neutral (45–55).")

    # Near-boundary caution: the 30/70 extremes carry the largest scoring swing,
    # so flag readings within a couple of points where the bin could flip.
    if abs(rsi - 70) <= _RSI_BOUNDARY_TOL or abs(rsi - 30) <= _RSI_BOUNDARY_TOL:
        reasoning.append(
            f"RSI {rsi:.0f} sits near an overbought/oversold boundary — "
            "the read may flip on a small move."
        )

    if price > ema20:
        bullish += 15
        reasoning.append("Price is trading above EMA20.")
    elif price < ema20:
        bearish += 15
        reasoning.append("Price is trading below EMA20.")

    if price > ema50:
        bullish += 15
        reasoning.append("Price is trading above EMA50.")
    elif price < ema50:
        bearish += 15
        reasoning.append("Price is trading below EMA50.")

    if macd["macd"] > macd["signal"]:
        bullish += 20
        reasoning.append("MACD is above the signal line, which is bullish.")
    elif macd["macd"] < macd["signal"]:
        bearish += 20
        reasoning.append("MACD is below the signal line, which is bearish.")

    if adx > 25:
        if bullish >= bearish:
            bullish += 20
        else:
            bearish += 20
        reasoning.append(f"ADX at {adx} confirms stronger directional conviction.")

    regime_name = regime["regime"]
    if regime_name in {"BULL_TREND", "NEUTRAL_BULLISH"}:
        bullish += 10
        reasoning.append(f"Market regime is {regime_name}, aligning with bullish setups.")
    elif regime_name in {"BEAR_TREND", "NEUTRAL_BEARISH"}:
        bearish += 10
        reasoning.append(f"Market regime is {regime_name}, aligning with bearish setups.")
    elif regime_name == "BREAKOUT_POTENTIAL":
        bullish += 5
        bearish += 5
        reasoning.append("Breakout potential is building, but direction still needs confirmation.")
    else:
        reasoning.append("Range-bound conditions reduce directional conviction.")

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
        reasoning.append("Bullish and bearish evidence is balanced.")

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
        "symbol": symbol.upper(),
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
        "data_basis": _data_basis(technicals),
    }


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
