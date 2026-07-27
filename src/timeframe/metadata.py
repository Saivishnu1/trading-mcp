"""Priority 2 — per-indicator metadata envelope.

src/meta.py already wraps every MCP tool RESPONSE in a trust envelope
(type/validation/data_quality/freshness/source) — that machinery is sound
and stays as-is. What it does not do is attach that context to each
INDICATOR VALUE individually: a response with five indicators gets one
freshness label for the whole payload, with no way to tell which specific
number came from which timeframe, candle, or source.

This module attaches that per-value context to everything flowing through
src.timeframe.engine.get_technicals() — the new, policy-validated gateway —
without touching the existing response-level envelope in meta.py or any
existing tool's output shape. Scope is deliberately narrow: this is not a
system-wide retrofit of every indicator-returning function.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Calculation periods hardcoded identically in both backends this engine
# dispatches to (src/analysis/regime.py's _analyze_technicals and
# src/chart_awareness/indicators.py's compute()) — kept here as the single
# place that documents what period each indicator name actually means,
# since neither backend exposes it as data today.
_CALCULATION_PERIOD = {
    "rsi": 14,
    "ema_20": 20,
    "ema_50": 20,   # EMA period is the number itself; kept for clarity/consistency
    "macd": 12,     # fast period; MACD is really (12, 26, 9) — see calculation_detail
    "adx": 14,
    "atr": 14,
}

_MACD_DETAIL = "fast=12, slow=26, signal=9"

# Sub-daily intervals go stale in minutes; EOD intervals are normal for
# hours. Matches src/tools/chart.py's analyze_chart threshold reasoning.
_INTRADAY_STALE_SECONDS = 180
_EOD_STALE_SECONDS = 5 * 86400  # 5 calendar days, matching regime.py's _STALENESS_CAUTION_DAYS


def _freshness_label(age_seconds: float | None, stale_threshold_seconds: int) -> str:
    if age_seconds is None:
        return "UNKNOWN"
    if age_seconds < 60:
        return "LIVE"
    if age_seconds <= stale_threshold_seconds:
        return "RECENT"
    return "STALE"


def _parse_candle_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _age_seconds(candle_timestamp: str | None) -> float | None:
    dt = _parse_candle_timestamp(candle_timestamp)
    if dt is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())


# Public aliases — src.timeframe.engine (Priority 3, freshness refusal) needs
# the same age/threshold logic this module already computes for the
# freshness LABEL, so refusal and labeling can never silently disagree.
candle_age_seconds = _age_seconds


def stale_threshold_seconds(timeframe: str) -> int:
    """The staleness threshold (seconds) for `timeframe` — the same value
    build_indicator_metadata uses internally to compute the freshness label."""
    return _INTRADAY_STALE_SECONDS if timeframe.endswith("minute") else _EOD_STALE_SECONDS


def build_indicator_metadata(
    indicator: str,
    value: object,
    *,
    timeframe: str,
    candle_timestamp: str | None,
    source: str | None,
    confidence: float | None = None,
) -> dict:
    """Build the per-indicator metadata envelope for one indicator value.

    Fields (per the phase brief): indicator, value, timeframe,
    candle_timestamp, source, freshness, confidence, calculation_period.

    confidence is explicitly None for pure technical indicators (RSI, EMA,
    MACD, ADX, ATR) — there is no model confidence for "what is RSI right
    now," only for a DERIVED judgment built on top of it (e.g. a regime
    classification or trade signal). Setting it to None here, not omitting
    the key, keeps the schema uniform and makes "no confidence applies"
    explicit rather than an accidental absence a caller could misread as
    "confidence unknown."
    """
    interval_is_intraday = timeframe.endswith("minute")
    stale_threshold = _INTRADAY_STALE_SECONDS if interval_is_intraday else _EOD_STALE_SECONDS
    age = _age_seconds(candle_timestamp)

    return {
        "indicator": indicator,
        "value": value,
        "timeframe": timeframe,
        "candle_timestamp": candle_timestamp,
        "source": source,
        "freshness": _freshness_label(age, stale_threshold),
        "confidence": confidence,
        "calculation_period": _CALCULATION_PERIOD.get(indicator),
        **({"calculation_detail": _MACD_DETAIL} if indicator == "macd" else {}),
    }


def build_indicator_metadata_list(technicals: dict) -> list[dict]:
    """Build the full per-indicator metadata list for a get_technicals()
    result — one entry per indicator value actually present (None values
    still get an entry; a missing/None value with metadata is more honest
    than silently dropping it, since the caller can then see WHY it's
    missing via freshness/source rather than just not finding the key)."""
    timeframe = technicals.get("interval", "unknown")
    candle_timestamp = technicals.get("last_candle_datetime") or technicals.get("last_candle_date")
    source = technicals.get("data_source")

    macd = technicals.get("macd") or {}
    adx = technicals.get("adx_14") or {}

    entries = [
        build_indicator_metadata("rsi", technicals.get("rsi_14"),
                                  timeframe=timeframe, candle_timestamp=candle_timestamp, source=source),
        build_indicator_metadata("ema_20", technicals.get("ema_20"),
                                  timeframe=timeframe, candle_timestamp=candle_timestamp, source=source),
        build_indicator_metadata("ema_50", technicals.get("ema_50"),
                                  timeframe=timeframe, candle_timestamp=candle_timestamp, source=source),
        build_indicator_metadata("macd", macd.get("macd"),
                                  timeframe=timeframe, candle_timestamp=candle_timestamp, source=source),
        build_indicator_metadata("adx", adx.get("adx"),
                                  timeframe=timeframe, candle_timestamp=candle_timestamp, source=source),
        build_indicator_metadata("atr", technicals.get("atr_14"),
                                  timeframe=timeframe, candle_timestamp=candle_timestamp, source=source),
    ]
    return entries
