from __future__ import annotations

from datetime import date, timedelta

from src.market import get_market
from src.technical import indicators

_INDEX_YF: dict[str, str] = {
    "NIFTY": "^NSEI",
    "NIFTY50": "^NSEI",
    "NIFTY 50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "NIFTY BANK": "^NSEBANK",
    "SENSEX": "^BSESN",
    "FINNIFTY": "^CNXFIN",
    "MIDCPNIFTY": "^NSEMDCP50",
}

_YF_INTERVALS = {
    "1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h",
    "1d", "5d", "1wk", "1mo", "3mo",
}
_INTERVAL_ALIAS: dict[str, str] = {
    "minute": "1m",
    "3minute": "5m",
    "5minute": "5m",
    "10minute": "15m",
    "15minute": "15m",
    "30minute": "30m",
    "60minute": "60m",
    "day": "1d",
}


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _error(symbol: str, message: str) -> dict:
    return {"symbol": symbol.upper(), "error": message}


def _resolve(symbol: str) -> str:
    return _INDEX_YF.get(symbol.upper().strip(), symbol)


def _resolve_interval(interval: str) -> str:
    value = interval.lower().strip()
    if value in _YF_INTERVALS:
        return value
    if value in _INTERVAL_ALIAS:
        return _INTERVAL_ALIAS[value]
    raise ValueError(f"unknown interval '{interval}'")


def _load_candles(symbol: str, interval: str = "day", lookback_days: int = 180) -> list[dict]:
    yf_symbol = _resolve(symbol)
    yf_interval = _resolve_interval(interval)
    today = date.today()
    start = (today - timedelta(days=lookback_days)).isoformat()
    end = (today + timedelta(days=1)).isoformat()
    return get_market().get_historical(yf_symbol, start, end, yf_interval)


def _extract_ohlc(candles: list[dict]) -> tuple[list[float], list[float], list[float]]:
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    return closes, highs, lows


def _analyze_technicals(symbol: str, interval: str = "day") -> dict:
    candles = _load_candles(symbol, interval=interval)
    if not candles:
        return _error(symbol, "no price data — check the symbol")

    closes, highs, lows = _extract_ohlc(candles)
    return {
        "symbol": symbol.upper(),
        "last_close": _round(closes[-1]),
        "rsi_14": indicators.rsi(closes, 14),
        "ema_20": indicators.ema(closes, 20),
        "ema_50": indicators.ema(closes, 50),
        "macd": indicators.macd(closes),
        "adx_14": indicators.adx(highs, lows, closes, 14),
        "atr_14": indicators.atr(highs, lows, closes, 14),
        "candles_used": len(candles),
    }


def detect_market_regime(symbol: str, interval: str = "day") -> dict:
    candles = _load_candles(symbol, interval=interval)
    if not candles:
        return _error(symbol, "no price data — check the symbol")

    closes, highs, lows = _extract_ohlc(candles)
    price = _round(closes[-1])
    ema20 = indicators.ema(closes, 20)
    ema50 = indicators.ema(closes, 50)
    adx_now = indicators.adx(highs, lows, closes, 14)
    atr_now = indicators.atr(highs, lows, closes, 14)

    if ema20 is None or ema50 is None or adx_now["adx"] is None or atr_now is None:
        return _error(symbol, "insufficient data for regime detection")

    prev_adx = indicators.adx(highs[:-1], lows[:-1], closes[:-1], 14) if len(closes) > 29 else {"adx": None}
    prev_atr = indicators.atr(highs[:-1], lows[:-1], closes[:-1], 14) if len(closes) > 15 else None

    adx_rising = prev_adx["adx"] is not None and adx_now["adx"] > prev_adx["adx"]
    atr_percent = (100.0 * atr_now / price) if price else 0.0
    atr_elevated = (
        (prev_atr is not None and atr_now > prev_atr)
        or atr_percent >= 1.5
    )

    regime = "NEUTRAL"
    confidence = 50

    if ema20 > ema50 and adx_now["adx"] > 25:
        regime = "BULL_TREND"
        confidence = min(100, int(60 + min(adx_now["adx"] - 25, 20) + min((ema20 - ema50) / max(price, 1) * 400, 20)))
    elif ema20 < ema50 and adx_now["adx"] > 25:
        regime = "BEAR_TREND"
        confidence = min(100, int(60 + min(adx_now["adx"] - 25, 20) + min((ema50 - ema20) / max(price, 1) * 400, 20)))
    elif adx_now["adx"] < 20:
        regime = "RANGE_BOUND"
        confidence = min(100, int(65 + min(20 - adx_now["adx"], 20)))
    elif adx_rising and atr_elevated:
        regime = "BREAKOUT_POTENTIAL"
        confidence = min(100, int(60 + min(max(adx_now["adx"] - (prev_adx["adx"] or 0), 0) * 4, 20) + min(atr_percent * 4, 20)))
    else:
        confidence = int(max(35, min(55, adx_now["adx"])))

    return {
        "symbol": symbol.upper(),
        "regime": regime,
        "confidence": confidence,
        "price": price,
        "ema20": ema20,
        "ema50": ema50,
        "adx": adx_now["adx"],
        "atr": atr_now,
    }


def calculate_risk_reward(entry: float, stoploss: float, target: float) -> dict:
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
    if capital <= 0 or risk_percent <= 0:
        return {"error": "capital and risk_percent must be greater than zero"}

    risk_per_unit = abs(entry - stoploss)
    risk_amount = capital * (risk_percent / 100.0)
    position_size = (risk_amount / risk_per_unit) if risk_per_unit else None

    return {
        "capital": _round(capital),
        "risk_percent": _round(risk_percent, 2),
        "risk_amount": _round(risk_amount),
        "position_size": _round(position_size) if position_size is not None else None,
    }


def generate_trade_setup(symbol: str) -> dict:
    technicals = _analyze_technicals(symbol)
    if "error" in technicals:
        return technicals

    regime = detect_market_regime(symbol)
    if "error" in regime:
        return regime

    price = technicals["last_close"]
    ema20 = technicals["ema_20"]
    ema50 = technicals["ema_50"]
    rsi = technicals["rsi_14"]
    macd = technicals["macd"]
    adx_info = technicals["adx_14"]
    atr = technicals["atr_14"]

    if None in (price, ema20, ema50, rsi, atr, adx_info["adx"], macd["macd"], macd["signal"]):
        return _error(symbol, "insufficient data for trade setup")

    buy_score = 0
    sell_score = 0
    reasoning: list[str] = []

    if ema20 > ema50:
        buy_score += 20
        reasoning.append("EMA20 is above EMA50, supporting bullish continuation.")
    elif ema20 < ema50:
        sell_score += 20
        reasoning.append("EMA20 is below EMA50, supporting bearish continuation.")

    if macd["macd"] > macd["signal"]:
        buy_score += 20
        reasoning.append("MACD is above its signal line, confirming bullish momentum.")
    elif macd["macd"] < macd["signal"]:
        sell_score += 20
        reasoning.append("MACD is below its signal line, confirming bearish momentum.")

    if rsi >= 55 and rsi < 70:
        buy_score += 20
        reasoning.append("RSI is in a healthy bullish range without being overbought.")
    elif rsi <= 45 and rsi > 30:
        sell_score += 20
        reasoning.append("RSI is in a healthy bearish range without being oversold.")

    if adx_info["adx"] >= 25:
        if buy_score >= sell_score:
            buy_score += 20
        else:
            sell_score += 20
        reasoning.append("ADX is above 25, indicating the prevailing move has strength.")

    if regime["regime"] == "BULL_TREND":
        buy_score += 20
        reasoning.append("Market regime is bullish trend, aligning with long setups.")
    elif regime["regime"] == "BEAR_TREND":
        sell_score += 20
        reasoning.append("Market regime is bearish trend, aligning with short setups.")
    elif regime["regime"] == "BREAKOUT_POTENTIAL":
        buy_score += 10
        sell_score += 10
        reasoning.append("Breakout conditions are building, so direction needs confirmation.")
    else:
        reasoning.append("Range-bound regime reduces directional conviction.")

    if buy_score > sell_score and buy_score >= 60:
        signal = "BUY"
        stoploss = _round(price - (atr * 1.5))
        target = _round(price + (atr * 3.0))
        confidence = buy_score
    elif sell_score > buy_score and sell_score >= 60:
        signal = "SELL"
        stoploss = _round(price + (atr * 1.5))
        target = _round(price - (atr * 3.0))
        confidence = sell_score
    else:
        signal = "NEUTRAL"
        stoploss = _round(price - atr)
        target = _round(price + atr)
        confidence = max(buy_score, sell_score)
        reasoning.append("Signals are mixed, so a neutral stance is more consistent.")

    return {
        "symbol": symbol.upper(),
        "signal": signal,
        "confidence": min(100, confidence),
        "entry": price,
        "stoploss": stoploss,
        "target": target,
        "reasoning": reasoning,
    }


def recommend_strategy(symbol: str) -> dict:
    technicals = _analyze_technicals(symbol)
    if "error" in technicals:
        return technicals

    regime = detect_market_regime(symbol)
    if "error" in regime:
        return regime

    rsi = technicals["rsi_14"]
    adx = technicals["adx_14"]["adx"]
    regime_name = regime["regime"]

    if regime_name == "BULL_TREND":
        if rsi is not None and rsi >= 60:
            strategy = "Long Call"
            reason = f"Bull trend with RSI at {rsi} and ADX at {adx} favors a directional upside trade."
        else:
            strategy = "Bull Call Spread"
            reason = f"Bull trend is present, but a spread keeps upside exposure defined while ADX is {adx}."
    elif regime_name == "BEAR_TREND":
        if rsi is not None and rsi <= 40:
            strategy = "Long Put"
            reason = f"Bear trend with RSI at {rsi} and ADX at {adx} favors a directional downside trade."
        else:
            strategy = "Bear Put Spread"
            reason = f"Bear trend is present, and a spread controls cost while ADX is {adx}."
    elif regime_name == "RANGE_BOUND":
        if rsi is not None and 40 <= rsi <= 60:
            strategy = "Iron Condor"
            reason = f"Low-trend conditions with RSI at {rsi} suggest price may stay contained."
        else:
            strategy = "Short Strangle"
            reason = f"Range behavior remains dominant, and RSI at {rsi} still supports premium-selling bias."
    else:
        if adx is not None and adx >= 22:
            strategy = "Long Straddle"
            reason = f"Rising trend strength and expanding volatility support a breakout strategy in either direction."
        else:
            strategy = "Long Strangle"
            reason = f"Breakout potential exists, and a strangle lowers cost while waiting for expansion."

    return {
        "symbol": symbol.upper(),
        "regime": regime_name,
        "strategy": strategy,
        "reason": reason,
    }
