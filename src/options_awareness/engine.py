"""
OptionsAwarenessEngine — orchestrates OI, IV, and level analysis.
"""
from __future__ import annotations

import logging

from src.options.analytics import _underlying

from .cache import cache_metadata, read_cache, write_cache
from .iv_analyzer import IVAnalyzer
from .levels import OILevelDetector
from .oi_analyzer import OIAnalyzer

_BSE_SYMBOLS = {"SENSEX", "BANKEX"}
logger = logging.getLogger(__name__)


def _fetch_live(symbol: str, expiry: str | None) -> tuple[dict, str | None]:
    """Fetch raw chain from NSE/BSE service (no cache)."""
    sym = symbol.upper().strip()
    if sym in _BSE_SYMBOLS:
        from src.options.bse_service import get_bse_options_service
        svc = get_bse_options_service()
    else:
        from src.options.service import get_options_service
        svc = get_options_service()

    metadata  = svc.get_option_chain(sym)
    available = metadata.get("records", {}).get("expiryDates", [])
    resolved  = expiry if expiry in available else (available[0] if available else None)
    chain     = svc.get_option_chain(sym, resolved)
    return chain, resolved


def _get_chain_with_cache(
    symbol: str,
    expiry: str | None,
) -> tuple[dict, str | None, dict | None]:
    """Return (chain, resolved_expiry, cache_meta).

    Strategy:
    - Try live fetch first.
    - On success → write to cache, return live data (cache_meta=None).
    - On failure → fall back to cached snapshot if available.
    - cache_meta is non-None only when serving from cache.
    """
    try:
        chain, resolved = _fetch_live(symbol, expiry)
        write_cache(symbol, expiry, chain, resolved)
        return chain, resolved, None
    except Exception as exc:
        logger.debug("Live fetch failed for %s: %s — checking cache", symbol, exc)

    entry = read_cache(symbol, expiry)
    if entry:
        logger.debug("Serving cached chain for %s (cached_at=%s)", symbol, entry.get("cached_at"))
        return entry["chain"], entry.get("resolved"), cache_metadata(entry)

    raise RuntimeError(f"No live data and no cached snapshot available for {symbol}")


def _build_observations(
    spot: float | None,
    walls: dict,
    levels: dict,
    iv_data: dict,
) -> list[str]:
    obs: list[str] = []

    call_wall = walls.get("call_wall")
    call_wall_oi = walls.get("call_wall_oi", 0)
    put_wall  = walls.get("put_wall")
    put_wall_oi = walls.get("put_wall_oi", 0)

    if call_wall is not None:
        oi_l = call_wall_oi / 100_000 if call_wall_oi else 0
        obs.append(f"Call wall at {call_wall:,.0f} — {oi_l:.1f}L OI")
    if put_wall is not None:
        oi_l = put_wall_oi / 100_000 if put_wall_oi else 0
        obs.append(f"Put wall at {put_wall:,.0f} — {oi_l:.1f}L OI")

    pcr = levels.get("pcr")
    pcr_interp = levels.get("pcr_interpretation", "")
    if pcr is not None:
        obs.append(f"PCR {pcr:.2f} — {pcr_interp}")

    max_pain = levels.get("max_pain")
    dist_mp  = levels.get("distance_from_max_pain")
    if max_pain is not None:
        dist_str = ""
        if dist_mp is not None:
            direction = "above" if dist_mp > 0 else "below"
            dist_str = f" — spot {abs(dist_mp):.0f} pts {direction}"
        obs.append(f"Max pain {max_pain:,.0f}{dist_str}")

    atm_iv = iv_data.get("atm_iv")
    if atm_iv is not None:
        obs.append(IVAnalyzer.get_atm_iv_interpretation(atm_iv))

    skew_interp = iv_data.get("skew_interpretation", "")
    iv_skew = iv_data.get("iv_skew")
    if iv_skew is not None and "insufficient" not in skew_interp:
        obs.append(skew_interp)

    return obs


class OptionsAwarenessEngine:

    def analyze(self, symbol: str, expiry: str | None = None) -> dict:
        """Run full option structure analysis for a symbol/expiry.

        Serves live data during market hours; falls back to the last cached
        EOD snapshot post-market. Result includes cache_status / cached_at /
        note fields when serving from cache.
        """
        sym = symbol.upper().strip()

        try:
            chain, resolved, cache_meta = _get_chain_with_cache(sym, expiry)
        except Exception as exc:
            return {
                "symbol": sym,
                "expiry": expiry,
                "error": str(exc),
                "spot": None,
                "pcr": None,
                "pcr_interpretation": "",
                "max_pain": None,
                "distance_from_max_pain": None,
                "iv": {},
                "walls": {},
                "oi_levels": {"supports": [], "resistances": []},
                "oi_structure": {"call_buildup": [], "put_buildup": [], "unwinding": []},
                "observations": [f"Option chain unavailable: {exc}"],
            }

        spot = _underlying(chain)

        walls    = OIAnalyzer.detect_walls(chain, resolved)
        oi_sr    = OIAnalyzer.detect_oi_support_resistance(chain, resolved)
        buildup  = OIAnalyzer.detect_oi_buildup(chain, resolved)
        iv_data  = IVAnalyzer.get_iv_surface(chain, resolved)
        levels   = OILevelDetector.get_key_levels(chain, resolved, oi_sr, walls)

        observations = _build_observations(spot, walls, levels, iv_data)
        if cache_meta:
            observations.insert(0, cache_meta["note"])

        result: dict = {
            "symbol":                 sym,
            "expiry":                 resolved,
            "spot":                   spot,
            "pcr":                    levels.get("pcr"),
            "pcr_interpretation":     levels.get("pcr_interpretation", ""),
            "max_pain":               levels.get("max_pain"),
            "distance_from_max_pain": levels.get("distance_from_max_pain"),
            "iv": {
                "atm_iv":            iv_data.get("atm_iv"),
                "atm_strike":        iv_data.get("atm_strike"),
                "iv_skew":           iv_data.get("iv_skew"),
                "skew_interpretation": iv_data.get("skew_interpretation", ""),
                "put_iv":            iv_data.get("put_iv"),
                "call_iv":           iv_data.get("call_iv"),
                "term_structure":    iv_data.get("term_structure", []),
            },
            "walls": {
                "call_wall":    walls.get("call_wall"),
                "call_wall_oi": walls.get("call_wall_oi", 0),
                "put_wall":     walls.get("put_wall"),
                "put_wall_oi":  walls.get("put_wall_oi", 0),
                "gamma_wall":   walls.get("gamma_wall"),
            },
            "oi_levels": {
                "supports":    oi_sr.get("supports", []),
                "resistances": oi_sr.get("resistances", []),
            },
            "oi_structure": buildup,
            "observations": observations,
        }

        if cache_meta:
            result["cache_status"] = cache_meta["cache_status"]
            result["cached_at"]    = cache_meta["cached_at"]
            result["note"]         = cache_meta["note"]

        return result
