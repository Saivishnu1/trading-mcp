from __future__ import annotations

from src.technical import indicators
from src.tools.technicals import _load_closes


def _error(symbol: str, message: str) -> dict:
    return {"symbol": symbol.upper(), "error": message}


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _validate_number(name: str, value: float) -> str | None:
    if value is None:
        return f"{name} is required"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number"
    if numeric <= 0:
        return f"{name} must be greater than zero"
    return None


def _analyze_technicals(symbol: str, lookback_days: int = 150) -> dict:
    """Reuse the same historical loader and indicator math as technical tools."""
    closes, highs, lows = _load_closes(symbol, lookback_days)
    if not closes:
        return _error(symbol, "no price data - check the symbol")

    last_close = round(closes[-1], 4)
    return {
        "symbol": symbol.upper(),
        "last_close": last_close,
        "candles_used": len(closes),
        "rsi_14": indicators.rsi(closes, 14),
        "ema_20": indicators.ema(closes, 20),
        "ema_50": indicators.ema(closes, 50),
        "macd": indicators.macd(closes),
        "adx_14": indicators.adx(highs, lows, closes, 14),
        "atr_14": indicators.atr(highs, lows, closes, 14),
    }


def detect_market_regime(symbol: str) -> dict:
    technicals = _analyze_technicals(symbol)
    if "error" in technicals:
        return technicals

    price = technicals["last_close"]
    rsi = technicals["rsi_14"]
    ema20 = technicals["ema_20"]
    ema50 = technicals["ema_50"]
    adx = technicals["adx_14"]["adx"]
    atr = technicals["atr_14"]

    if None in (price, rsi, ema20, ema50, adx, atr):
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
        "confidence": confidence,
        "price": price,
        "rsi": rsi,
        "ema20": ema20,
        "ema50": ema50,
        "adx": adx,
        "atr": atr,
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

    if None in (price, rsi, ema20, ema50, adx, atr, macd["macd"], macd["signal"]):
        return _error(symbol, "insufficient data for trade setup")

    bullish = 0
    bearish = 0
    reasoning: list[str] = []

    if rsi > 55:
        bullish += 20
        reasoning.append(f"RSI at {rsi} is above 55, favoring bullish momentum.")
    elif rsi < 45:
        bearish += 20
        reasoning.append(f"RSI at {rsi} is below 45, favoring bearish momentum.")
    else:
        reasoning.append(f"RSI at {rsi} is neutral.")

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

    entry_above = _round(price + (atr * 0.25))
    entry_below = _round(price - (atr * 0.25))
    bull_target = _round(price + (atr * 1.5))
    bear_target = _round(price - (atr * 1.5))

    # Legacy scalar fields — derived from zone fields so both schemas stay in sync.
    # BUY / NEUTRAL_BULLISH: enter on breakout above, target up, stop below.
    # SELL / NEUTRAL_BEARISH: enter on breakdown below, target down, stop above.
    # NEUTRAL: symmetric zone around price.
    if signal in {"BUY", "NEUTRAL_BULLISH"}:
        entry_scalar = entry_above
        stoploss_scalar = _round(price - (atr * 1.5))
        target_scalar = bull_target
    elif signal in {"SELL", "NEUTRAL_BEARISH"}:
        entry_scalar = entry_below
        stoploss_scalar = _round(price + (atr * 1.5))
        target_scalar = bear_target
    else:  # NEUTRAL
        entry_scalar = _round(price)
        stoploss_scalar = _round(price - atr)
        target_scalar = _round(price + atr)

    return {
        "symbol": symbol.upper(),
        "signal": signal,
        "confidence": min(100, confidence),
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
