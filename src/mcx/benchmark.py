"""MCX vs. international-benchmark divergence check (Priority A4).

Only covers CRUDEOIL/CRUDEOILM (WTI) and NATURALGAS/NATGASMINI (Henry Hub) —
the two commodities with a real benchmark source (src/mcx/benchmark_sources.py).
There is no working MCX-side price source in this codebase (see
docs/research/mcx_scope_20260711.md), so the caller supplies the MCX contract's
own % change explicitly rather than this module fetching it.
"""
from __future__ import annotations

import threading
import time

from src.mcx.benchmark_sources import COMMODITY_CODES, fetch_benchmark_change_pct

_TTL = 900  # 15 minutes
_CACHE: dict[str, tuple[float | None, float]] = {}
_LOCK = threading.Lock()


def _cached_benchmark_change_pct(commodity_code: str) -> tuple[float | None, bool]:
    """Returns (change_pct, from_cache)."""
    with _LOCK:
        if commodity_code in _CACHE:
            value, ts = _CACHE[commodity_code]
            if time.monotonic() - ts < _TTL:
                return value, True

    value = fetch_benchmark_change_pct(commodity_code)
    with _LOCK:
        _CACHE[commodity_code] = (value, time.monotonic())
    return value, False


def check_benchmark_divergence(
    symbol: str, mcx_change_pct: float, threshold_pct: float = 3.0,
) -> dict:
    """Compare a caller-supplied MCX % change against the real international
    benchmark's own % change. Returns a dict with an "error" key if the
    symbol isn't covered or the benchmark fetch failed — never raises."""
    symbol_upper = symbol.upper().strip()
    commodity_code = COMMODITY_CODES.get(symbol_upper)
    if commodity_code is None:
        return {
            "error": "unsupported_symbol",
            "message": (
                f"No benchmark source for {symbol_upper}. Supported: "
                f"{sorted(set(COMMODITY_CODES))}."
            ),
        }

    benchmark_change_pct, from_cache = _cached_benchmark_change_pct(commodity_code)
    if benchmark_change_pct is None:
        return {
            "error": "benchmark_source_unavailable",
            "message": "Could not fetch the international benchmark price right now.",
            "symbol": symbol_upper,
            "from_cache": from_cache,
        }

    divergence_pct = round(abs(mcx_change_pct - benchmark_change_pct), 4)
    flag = None
    if divergence_pct > threshold_pct:
        flag = (
            f"MCX {symbol_upper} moved {mcx_change_pct:+.2f}% while the "
            f"international benchmark moved {benchmark_change_pct:+.2f}% — "
            f"local move may be liquidity/INR-driven, not fundamentals-driven."
        )

    return {
        "symbol": symbol_upper,
        "mcx_change_pct": mcx_change_pct,
        "benchmark_change_pct": benchmark_change_pct,
        "divergence_pct": divergence_pct,
        "flag": flag,
        "from_cache": from_cache,
    }
