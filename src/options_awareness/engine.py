"""
OptionsAwarenessEngine — orchestrates OI, IV, and level analysis.
"""
from __future__ import annotations

from src.options.analytics import _underlying
from .oi_analyzer import OIAnalyzer
from .iv_analyzer import IVAnalyzer
from .levels import OILevelDetector

_BSE_SYMBOLS = {"SENSEX", "BANKEX"}


def _get_chain(symbol: str, expiry: str | None) -> tuple[dict, str | None]:
    """Fetch raw chain dict and resolved expiry from the appropriate service."""
    sym = symbol.upper().strip()
    if sym in _BSE_SYMBOLS:
        from src.options.bse_service import get_bse_options_service
        svc = get_bse_options_service()
    else:
        from src.options.service import get_options_service
        svc = get_options_service()

    metadata   = svc.get_option_chain(sym)
    available  = metadata.get("records", {}).get("expiryDates", [])
    resolved   = expiry if expiry in available else (available[0] if available else None)
    chain      = svc.get_option_chain(sym, resolved)
    return chain, resolved


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
        """Run full option structure analysis for a symbol/expiry."""
        sym = symbol.upper().strip()

        try:
            chain, resolved = _get_chain(sym, expiry)
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

        return {
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
