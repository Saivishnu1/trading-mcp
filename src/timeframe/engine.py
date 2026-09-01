"""Timeframe Engine — Priority 1 (timeframe policy) + Priority 3 (freshness refusal).

Single gateway a recommendation-facing caller must go through to get
technicals for a specific (holding_horizon, interval) pair. Refuses
(returns an error dict, never raises) when the requested interval has no
role at all under the given horizon's policy — the architectural guarantee
the phase asked for: "no component may directly consume indicators without
timeframe validation" becomes "no component gets technicals out of this
engine without the pair being policy-checked first."

Priority 3 adds a second refusal axis, independent of the timeframe-policy
one above: staleness. Every existing staleness mechanism in this codebase
(src/analysis/regime.py's _data_basis/_staleness_days, src/meta.py's
DQ_STALE) only ever produces a caution string — nothing anywhere actually
refuses to hand back stale data. This module is the first place that does:
  - EXECUTION/FINE_ENTRY role: a stale candle is refused outright (error,
    not caution) — this is the timeframe an entry decision would actually
    be gated on, so stale data here is the exact "wrong data drove a wrong
    entry" failure mode this phase exists to prevent.
  - CONTEXT role: staleness degrades to a caution field, not a refusal —
    context is advisory by definition; refusing an otherwise-valid
    EXECUTION setup just because CONTEXT happened to be stale would make
    the CONTEXT check actively harmful rather than merely informative.
Thresholds match src.timeframe.metadata's freshness classification: 180s
for intraday intervals, 5 calendar days for EOD (day/week/month).

This does not replace src/analysis/regime.py's _analyze_technicals or
src/chart_awareness/engine.py's ChartEngine — it is a thin, validating
dispatcher in front of them, reusing whichever one actually serves the
requested interval:
  - "day"/"week"/"month"  -> _analyze_technicals (yfinance EOD, existing
    regime/setup call chain's data source — unchanged for those paths)
  - "1minute".."60minute" -> ChartEngine (Zerodha/INDmoney/Yahoo tiered
    intraday fetcher — the only backend in this codebase that can serve
    sub-daily candles at all)

Existing functions (detect_market_regime, generate_trade_setup,
recommend_strategy, create_trade_plan, recommend_trade, ...) are NOT
modified or routed through this engine — per the explicit decision for this
phase, this ships as new, parallel, opt-in functionality so nothing already
in production changes behavior. See src/analysis/regime.py's
generate_trade_setup_tf for the first (and, for now, only) consumer.
"""
from __future__ import annotations

from src.timeframe.metadata import (
    build_indicator_metadata_list,
    candle_age_seconds,
    stale_threshold_seconds,
)
from src.timeframe.policy import (
    HoldingHorizon,
    TimeframeRole,
    can_gate_entry,
    role_for,
)


def _apply_freshness_gate(result: dict, horizon: HoldingHorizon, interval: str, role: TimeframeRole) -> dict:
    """Priority 3 — act on staleness instead of only labeling it.

    EXECUTION/FINE_ENTRY: stale candle -> replace `result` with a refusal
    (error dict), never hand back the data. CONTEXT: stale candle -> keep
    the data, add a `staleness_caution` field; still usable as context,
    just flagged. No timestamp at all -> treated as unknown, not stale
    (can't refuse on data you can't measure the age of — that would refuse
    legitimate responses whose backend simply doesn't report the field).
    """
    candle_timestamp = result.get("last_candle_datetime") or result.get("last_candle_date")
    age = candle_age_seconds(candle_timestamp)
    if age is None:
        return result

    threshold = stale_threshold_seconds(interval)
    if age <= threshold:
        return result

    age_desc = f"{age:.0f}s old (threshold {threshold}s) as of candle_timestamp={candle_timestamp!r}"
    if role in (TimeframeRole.EXECUTION, TimeframeRole.FINE_ENTRY):
        return {
            "error": (
                f"stale data refused: interval={interval!r} candle is {age_desc}. "
                f"This interval is role={role.value} under horizon={horizon.value} — "
                "an EXECUTION/FINE_ENTRY read must be fresh to gate an entry. "
                "Retry, or fall back to a coarser interval this horizon still "
                "permits as EXECUTION."
            ),
            "symbol": result.get("symbol"),
            "horizon": horizon.value,
            "interval": interval,
            "role": role.value,
            "staleness_seconds": age,
        }

    result["staleness_caution"] = (
        f"CONTEXT-role data is {age_desc} — still usable as context, but do "
        "not treat it as a fresh confirming/opposing read."
    )
    return result

_YFINANCE_BACKED_INTERVALS = frozenset({"day", "week", "month"})

# regime._analyze_technicals's friendly names for its own interval param —
# distinct from chart_awareness's interval vocabulary, translated here so
# this module is the one place that knows both naming schemes exist.
_TO_REGIME_INTERVAL = {"day": "daily", "week": "weekly", "month": "monthly"}


def get_technicals(
    symbol: str,
    horizon: HoldingHorizon,
    interval: str,
    *,
    lookback_days: int = 150,
    chart_days: int = 90,
) -> dict:
    """Return technicals for (symbol, interval), tagged with the role this
    interval plays under `horizon`'s policy. Refuses with an "error" key —
    never raises, never silently substitutes a different interval — when
    `interval` has no defined role under `horizon` at all.

    Callers that need to gate an entry decision must check
    result["role"] in ("EXECUTION", "FINE_ENTRY") — CONTEXT-role results are
    valid, real data, just not permitted to trigger/block a trade by
    themselves under this horizon.
    """
    role = role_for(horizon, interval)
    if role == TimeframeRole.DISALLOWED:
        return {
            "error": (
                f"interval={interval!r} has no defined role under "
                f"horizon={horizon.value} — this pairing is outside the "
                "Timeframe Engine's policy for this holding horizon, not "
                "merely discouraged. See src/timeframe/policy.py POLICY."
            ),
            "symbol": symbol.upper() if isinstance(symbol, str) else symbol,
            "horizon": horizon.value,
            "interval": interval,
        }

    if interval in _YFINANCE_BACKED_INTERVALS:
        from src.analysis.regime import _analyze_technicals
        regime_interval = _TO_REGIME_INTERVAL[interval]
        technicals = _analyze_technicals(symbol, lookback_days=lookback_days, interval=regime_interval)
        if "error" in technicals:
            return technicals
        result = {
            **technicals,
            "horizon": horizon.value,
            "interval": interval,
            "role": role.value,
            "can_gate_entry": can_gate_entry(horizon, interval),
        }
        # Priority 2 — per-indicator metadata, additive (doesn't replace the
        # flat rsi_14/ema_20/... fields Priority 1's callers already use).
        result["indicator_metadata"] = build_indicator_metadata_list(result)
        return _apply_freshness_gate(result, horizon, interval, role)

    # Sub-daily interval — only ChartEngine's tiered intraday fetcher can serve this.
    # asyncio.run() from sync code matches the existing precedent in
    # src/tools/technicals.py::_load_candles_tiered and src/market/calendar.py
    # for bridging into this same async fetch stack from a sync caller. If a
    # loop is already running (this function called from async code, e.g. a
    # test under pytest-anyio, or a future async caller), run the fetch on a
    # separate thread with its own loop instead of asyncio.run() raising.
    import asyncio

    from src.chart_awareness.engine import ChartEngine

    async def _fetch() -> dict:
        return await ChartEngine().analyze(symbol, interval=interval, days=chart_days)

    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            chart_result = asyncio.run(_fetch())
        else:
            # A loop is already running in this thread (e.g. this function
            # called from async code, or a test under pytest-anyio) —
            # asyncio.run() would raise here. Run on a separate thread with
            # its own loop instead. Pass the coroutine FUNCTION, not a
            # pre-created coroutine object — asyncio.run(_fetch()) would
            # create the coroutine in THIS thread and hand it to the worker
            # thread's event loop, which is the wrong loop to have created
            # it against and can leave it uncollected/never-awaited if the
            # submit races the outer `with` block's cleanup.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                chart_result = pool.submit(lambda: asyncio.run(_fetch())).result()
    except Exception as exc:
        return {
            "error": f"intraday chart fetch failed: {exc}",
            "symbol": symbol.upper() if isinstance(symbol, str) else symbol,
            "horizon": horizon.value,
            "interval": interval,
        }
    if "error" in chart_result:
        return {
            "error": chart_result["error"],
            "symbol": symbol.upper() if isinstance(symbol, str) else symbol,
            "horizon": horizon.value,
            "interval": interval,
        }

    ind = chart_result.get("indicators") or {}
    # Normalize ChartEngine's flat indicator names (ema20, rsi, adx, ...) into
    # the same shape _analyze_technicals produces (ema_20, rsi_14,
    # adx_14={"adx":...}, last_close) so _score_setup/_classify_regime work
    # identically regardless of which backend actually served the candles —
    # they must not know or care that a different fetcher was used.
    result = {
        "symbol": chart_result.get("symbol"),
        "last_close": chart_result.get("last_close"),
        "candles_used": chart_result.get("candles_analyzed"),
        "data_source": chart_result.get("data_source"),
        "last_candle_date": chart_result.get("last_candle_datetime"),
        "last_candle_datetime": chart_result.get("last_candle_datetime"),
        "rsi_14": ind.get("rsi"),
        "ema_20": ind.get("ema20"),
        "ema_50": ind.get("ema50"),
        "macd": {
            "macd": ind.get("macd"),
            "signal": ind.get("macd_signal"),
            "histogram": ind.get("macd_histogram"),
        },
        "adx_14": {"adx": ind.get("adx")},
        "atr_14": ind.get("atr"),
        "horizon": horizon.value,
        "interval": interval,
        "role": role.value,
        "can_gate_entry": can_gate_entry(horizon, interval),
    }
    result["indicator_metadata"] = build_indicator_metadata_list(result)
    return _apply_freshness_gate(result, horizon, interval, role)
