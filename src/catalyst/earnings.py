"""
Earnings calendar + corporate actions — Phase 11B.

Fetches the next earnings date, EPS/revenue estimates, and upcoming
dividends/splits via yfinance.Ticker.calendar and .actions.

Corporate actions (dividends, splits) within the next 30 days are returned
as structured lists so callers can build catalyst timelines.

Cache TTL: 3600 s (1 hour) — earnings calendar changes slowly.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, timedelta

from src.catalyst.constants import CATALYST_PRIORITY, _to_yf_ticker, is_index

logger = logging.getLogger(__name__)

_TTL = 3600
_CACHE: dict[str, tuple[dict, float]] = {}
_LOCK = threading.Lock()

_CORPORATE_ACTIONS_HORIZON = 30  # days to look ahead for dividends/splits


# ---------------------------------------------------------------------------
# yfinance integration — patchable factory
# ---------------------------------------------------------------------------

def _get_ticker(yf_ticker: str):
    import yfinance as yf
    return yf.Ticker(yf_ticker)


# ---------------------------------------------------------------------------
# Proximity scoring
# ---------------------------------------------------------------------------

def _earnings_proximity(days: int | None) -> tuple[str, int]:
    """Return (risk_label, score 0-100) based on days until earnings."""
    if days is None:
        return "LOW", 10
    if days <= 1:
        return "IMMINENT", 100
    if days <= 3:
        return "VERY_HIGH", 80
    if days <= 7:
        return "HIGH", 60
    if days <= 14:
        return "MEDIUM", 30
    return "LOW", 10


def _corporate_action_risk(dividends: list[dict], splits: list[dict]) -> str:
    """Summarise corporate action risk based on upcoming events."""
    all_days = [d["days_until"] for d in dividends + splits]
    if not all_days:
        return "LOW"
    nearest = min(all_days)
    if nearest <= 3:
        return "HIGH"
    if nearest <= 7:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# yfinance data parsers — accept raw calendar/actions objects, not ticker
# Property access is done in get_earnings_calendar so exceptions propagate
# ---------------------------------------------------------------------------

def _parse_calendar(cal) -> tuple[str | None, float | None, float | None]:
    """Extract (next_earnings_date, eps_estimate, revenue_estimate) from
    a raw yfinance calendar object (DataFrame or dict).

    Returns (None, None, None) on any parse error or missing data.
    Does NOT access yfinance properties — caller does that.
    """
    if cal is None:
        return None, None, None

    try:
        # DataFrame-like: has .columns and supports col[key] iteration
        if hasattr(cal, "columns"):
            data: dict = {}
            for col in cal.columns:
                vals = cal[col].dropna().tolist()
                data[col] = vals[0] if vals else None
        elif isinstance(cal, dict):
            data = cal
        else:
            return None, None, None

        # Earnings Date
        raw_date = data.get("Earnings Date")
        if raw_date is None:
            return None, None, None

        # raw_date can be a Timestamp, date, string, or list
        if isinstance(raw_date, list):
            raw_date = raw_date[0] if raw_date else None
        if raw_date is None:
            return None, None, None

        try:
            if hasattr(raw_date, "date"):
                next_date = raw_date.date().isoformat()
            elif hasattr(raw_date, "isoformat"):
                next_date = raw_date.isoformat()[:10]
            else:
                next_date = str(raw_date)[:10]
        except Exception:
            next_date = None

        eps_est = data.get("Earnings Average") or data.get("EPS Estimate")
        rev_est = data.get("Revenue Average") or data.get("Revenue Estimate")

        try:
            eps_est = float(eps_est) if eps_est is not None else None
        except (TypeError, ValueError):
            eps_est = None
        try:
            rev_est = float(rev_est) if rev_est is not None else None
        except (TypeError, ValueError):
            rev_est = None

        return next_date, eps_est, rev_est

    except Exception as exc:
        logger.debug("calendar parse error: %s", exc)
        return None, None, None


def _parse_actions(actions_df, days_ahead: int = _CORPORATE_ACTIONS_HORIZON) -> tuple[list, list]:
    """Return (upcoming_dividends, upcoming_splits) within *days_ahead* days.

    Accepts a raw yfinance actions DataFrame (or None).
    Does NOT access yfinance properties — caller does that.
    """
    dividends: list[dict] = []
    splits: list[dict] = []

    if actions_df is None:
        return [], []

    try:
        if hasattr(actions_df, "empty") and actions_df.empty:
            return [], []

        today = date.today()
        cutoff = today + timedelta(days=days_ahead)

        for idx, row in actions_df.iterrows():
            try:
                ex_date = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
            except Exception:
                continue

            if ex_date < today or ex_date > cutoff:
                continue

            days_until = (ex_date - today).days
            ex_date_str = ex_date.isoformat()

            div_amount = float(row.get("Dividends", 0) or 0)
            split_ratio = float(row.get("Stock Splits", 0) or 0)

            if div_amount > 0:
                dividends.append({
                    "ex_date":    ex_date_str,
                    "amount":     round(div_amount, 4),
                    "days_until": days_until,
                    "type":       "DIVIDEND",
                })
            if split_ratio > 0:
                splits.append({
                    "ex_date":    ex_date_str,
                    "ratio":      split_ratio,
                    "days_until": days_until,
                    "type":       "SPLIT",
                })

    except Exception as exc:
        logger.debug("actions parse error: %s", exc)

    return dividends, splits


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_earnings_calendar(symbol: str) -> dict:
    """Fetch next earnings date, EPS/revenue estimates, and upcoming corporate actions.

    For index symbols (NIFTY, BANKNIFTY) earnings are not applicable;
    a structured response is still returned with null date fields and a note.

    Cache TTL: 3600 s.
    """
    yf_ticker = _to_yf_ticker(symbol)
    cache_key = f"earnings_{yf_ticker}"

    with _LOCK:
        if cache_key in _CACHE:
            result, ts = _CACHE[cache_key]
            if time.monotonic() - ts < _TTL:
                return result

    sym_upper = symbol.upper().strip().split(":")[-1]

    # Index symbols — earnings not applicable
    if is_index(yf_ticker):
        result = {
            "symbol":                  sym_upper,
            "yf_ticker":               yf_ticker,
            "next_earnings_date":      None,
            "days_until_earnings":     None,
            "earnings_proximity_risk": "N/A",
            "earnings_proximity_score": 0,
            "eps_estimate":            None,
            "revenue_estimate":        None,
            "upcoming_dividends":      [],
            "upcoming_splits":         [],
            "corporate_action_risk":   "N/A",
            "note": "Index symbol — earnings calendar not applicable.",
        }
        with _LOCK:
            _CACHE[cache_key] = (result, time.monotonic())
        return result

    # Property access in outer try so yfinance exceptions surface as "error"
    try:
        ticker = _get_ticker(yf_ticker)
        raw_calendar = ticker.calendar   # may raise
        raw_actions = ticker.actions     # may raise
    except Exception as exc:
        logger.debug("yfinance fetch failed for %s: %s", yf_ticker, exc)
        return {
            "symbol":                  sym_upper,
            "yf_ticker":               yf_ticker,
            "next_earnings_date":      None,
            "days_until_earnings":     None,
            "earnings_proximity_risk": "LOW",
            "earnings_proximity_score": 10,
            "eps_estimate":            None,
            "revenue_estimate":        None,
            "upcoming_dividends":      [],
            "upcoming_splits":         [],
            "corporate_action_risk":   "LOW",
            "error":                   str(exc),
        }

    next_date, eps_est, rev_est = _parse_calendar(raw_calendar)
    dividends, splits = _parse_actions(raw_actions)

    # Compute days until earnings
    days_until: int | None = None
    if next_date:
        try:
            days_until = (date.fromisoformat(next_date) - date.today()).days
            if days_until < 0:
                # Past earnings date → treat as no upcoming date
                next_date = None
                days_until = None
        except Exception:
            days_until = None

    prox_risk, prox_score = _earnings_proximity(days_until)
    corp_risk = _corporate_action_risk(dividends, splits)

    result = {
        "symbol":                   sym_upper,
        "yf_ticker":                yf_ticker,
        "next_earnings_date":       next_date,
        "days_until_earnings":      days_until,
        "earnings_proximity_risk":  prox_risk,
        "earnings_proximity_score": prox_score,
        "eps_estimate":             eps_est,
        "revenue_estimate":         rev_est,
        "upcoming_dividends":       dividends,
        "upcoming_splits":          splits,
        "corporate_action_risk":    corp_risk,
    }

    with _LOCK:
        _CACHE[cache_key] = (result, time.monotonic())
    return result
