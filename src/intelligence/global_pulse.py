"""
Global macro pulse — Phase 10.

Fetches crude oil, gold, dollar index, S&P 500, and US 10Y yield via the
existing market service (yfinance-backed). One call per asset, cached together.

Cache TTL: 300 s (5 min).
"""
from __future__ import annotations

import threading
import time
from datetime import date, timedelta

from src.market import get_market

_TTL = 300
_CACHE: dict[str, tuple[dict, float]] = {}
_LOCK = threading.Lock()

_ASSETS: dict[str, dict] = {
    "crude_oil":    {"ticker": "CL=F",     "name": "Crude Oil (WTI)"},
    "gold":         {"ticker": "GC=F",      "name": "Gold"},
    "dxy":          {"ticker": "DX-Y.NYB",  "name": "US Dollar Index"},
    "sp500":        {"ticker": "^GSPC",     "name": "S&P 500"},
    "us_10y_yield": {"ticker": "^TNX",      "name": "US 10Y Yield"},
}

_LOOKBACK_DAYS = 7  # enough to get 2 trading days


def _india_impact(key: str, change_pct: float) -> str:
    if key == "crude_oil":
        if change_pct > 2:
            return "Rising energy costs — inflationary pressure, hawkish risk for RBI"
        if change_pct < -2:
            return "Falling crude — deflationary relief, supportive for India"
        return "Crude stable — neutral for India"
    if key == "gold":
        if change_pct > 1:
            return "Safe-haven buying — risk-off sentiment globally"
        if change_pct < -1:
            return "Gold falling — risk-on globally, positive for equities"
        return "Gold stable"
    if key == "dxy":
        if change_pct > 0.5:
            return "Dollar strengthening — FII outflow pressure on Indian markets"
        if change_pct < -0.5:
            return "Dollar weakening — supportive for FII inflows to India"
        return "Dollar stable — neutral for FII flows"
    if key == "sp500":
        if change_pct > 1:
            return "US strength — positive sentiment spillover for Indian markets"
        if change_pct < -1:
            return "US risk-off — likely gap-down pressure on Indian markets"
        return "US markets stable"
    if key == "us_10y_yield":
        if change_pct > 2:
            return "US yields rising sharply — pressure on equity valuations and INR"
        if change_pct < -2:
            return "US yields falling — positive for equity valuations"
        return "US yields stable"
    return "No interpretation available"


def _overall_sentiment(assets: dict) -> str:
    """Simple vote: each strongly negative signal is risk-off, positive is risk-on."""
    risk_off = 0
    risk_on = 0
    for key, data in assets.items():
        cp = data.get("change_pct")
        if cp is None:
            continue
        if key == "sp500":
            if cp < -1:
                risk_off += 2
            elif cp > 1:
                risk_on += 2
        if key == "gold" and cp > 1:
            risk_off += 1
        if key == "dxy":
            if cp > 0.5:
                risk_off += 1
            elif cp < -0.5:
                risk_on += 1
        if key == "crude_oil" and cp < -2:
            risk_on += 1
    if risk_off >= 2:
        return "RISK_OFF"
    if risk_on >= 2:
        return "RISK_ON"
    return "NEUTRAL"


def get_global_pulse() -> dict:
    """Return a snapshot of global macro signals relevant to Indian equity markets."""
    cache_key = "global_pulse"
    with _LOCK:
        if cache_key in _CACHE:
            result, ts = _CACHE[cache_key]
            if time.monotonic() - ts < _TTL:
                return result

    try:
        today = date.today()
        start = (today - timedelta(days=_LOOKBACK_DAYS)).isoformat()
        end = (today + timedelta(days=1)).isoformat()

        asset_data: dict[str, dict] = {}
        svc = get_market()

        for asset_key, meta in _ASSETS.items():
            try:
                candles = svc.get_historical(meta["ticker"], start, end, "1d")
                if candles and len(candles) >= 2:
                    last = round(candles[-1]["close"], 4)
                    prev = round(candles[-2]["close"], 4)
                    chg = round((last - prev) / prev * 100, 2)
                elif candles:
                    last = round(candles[-1]["close"], 4)
                    prev = chg = None
                else:
                    last = prev = chg = None
            except Exception:
                last = prev = chg = None

            asset_data[asset_key] = {
                "name":        meta["name"],
                "last":        last,
                "prev_close":  prev,
                "change_pct":  chg,
                "india_impact": (
                    _india_impact(asset_key, chg)
                    if chg is not None
                    else "Data unavailable"
                ),
            }

        result = {
            "assets":            asset_data,
            "overall_sentiment": _overall_sentiment(asset_data),
        }
    except Exception as exc:
        return {"error": str(exc)}

    with _LOCK:
        _CACHE[cache_key] = (result, time.monotonic())
    return result
