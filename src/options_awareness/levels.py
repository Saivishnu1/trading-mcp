"""
OI-derived key levels — aggregates wall, max pain, PCR, and S/R into one dict.
"""
from __future__ import annotations

from src.options.analytics import calculate_max_pain, calculate_pcr, _underlying


class OILevelDetector:

    @staticmethod
    def get_key_levels(
        chain: dict,
        expiry: str | None,
        oi_sr: dict,
        walls: dict,
    ) -> dict:
        """Aggregate all OI-derived levels into a single dict.

        Args:
            chain:   Raw NSE/BSE chain dict
            expiry:  Resolved expiry string
            oi_sr:   Output of OIAnalyzer.detect_oi_support_resistance()
            walls:   Output of OIAnalyzer.detect_walls()
        """
        spot = _underlying(chain)
        pcr_data = calculate_pcr(chain, expiry)
        mp_data  = calculate_max_pain(chain, expiry)

        pcr     = pcr_data.get("pcr_oi")
        max_pain = mp_data.get("max_pain")

        dist_from_mp = None
        if spot is not None and max_pain is not None:
            dist_from_mp = round(float(spot) - float(max_pain), 2)

        return {
            "call_wall":              walls.get("call_wall"),
            "call_wall_oi":           walls.get("call_wall_oi", 0),
            "put_wall":               walls.get("put_wall"),
            "put_wall_oi":            walls.get("put_wall_oi", 0),
            "gamma_wall":             walls.get("gamma_wall"),
            "max_pain":               max_pain,
            "distance_from_max_pain": dist_from_mp,
            "pcr":                    pcr,
            "pcr_interpretation":     pcr_data.get("interpretation", ""),
            "supports":               oi_sr.get("supports", []),
            "resistances":            oi_sr.get("resistances", []),
        }
