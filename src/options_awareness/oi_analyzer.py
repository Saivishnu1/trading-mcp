"""
OI structure analysis — walls, buildup detection, and OI-derived S/R levels.

Works on the raw NSE/BSE chain dict (records.data format).
"""
from __future__ import annotations

from src.options.analytics import _strikes_for_expiry, _underlying


# How many top strikes to surface for walls / S/R
_TOP_N = 5
# OI change threshold for buildup/unwinding: must differ from zero
_OI_CHANGE_MIN = 0


def _oi_strength(oi: int, max_oi: int) -> str:
    if max_oi <= 0:
        return "weak"
    ratio = oi / max_oi
    if ratio >= 0.7:
        return "strong"
    if ratio >= 0.4:
        return "moderate"
    return "weak"


class OIAnalyzer:

    @staticmethod
    def detect_walls(chain: dict, expiry: str | None = None) -> dict:
        """Call wall = strike with highest call OI; put wall = highest put OI.

        Returns top-3 each plus a gamma_wall proxy (highest OI closest to spot).
        """
        rows = _strikes_for_expiry(chain, expiry)
        spot = _underlying(chain) or 0.0

        call_rows: list[dict] = []
        put_rows: list[dict] = []

        for r in rows:
            sp = r.get("strikePrice")
            ce = r.get("CE") or {}
            pe = r.get("PE") or {}
            if ce:
                call_rows.append({
                    "strike": sp,
                    "oi": ce.get("openInterest", 0) or 0,
                    "iv": ce.get("impliedVolatility"),
                })
            if pe:
                put_rows.append({
                    "strike": sp,
                    "oi": pe.get("openInterest", 0) or 0,
                    "iv": pe.get("impliedVolatility"),
                })

        top_calls = sorted(call_rows, key=lambda x: x["oi"], reverse=True)[:3]
        top_puts  = sorted(put_rows,  key=lambda x: x["oi"], reverse=True)[:3]

        # Gamma wall proxy: highest OI strike nearest to spot
        all_oi = [(r["strike"], r["oi"]) for r in call_rows + put_rows if r["oi"] > 0]
        if all_oi and spot:
            # Score by OI weighted by proximity to spot
            def _gamma_score(item):
                s, o = item
                dist = abs(s - spot) / max(spot, 1)
                return o / (1 + dist * 10)
            gamma_wall = max(all_oi, key=_gamma_score)[0]
        else:
            gamma_wall = top_calls[0]["strike"] if top_calls else None

        return {
            "call_wall":     top_calls[0]["strike"] if top_calls else None,
            "call_wall_oi":  top_calls[0]["oi"]     if top_calls else 0,
            "put_wall":      top_puts[0]["strike"]  if top_puts  else None,
            "put_wall_oi":   top_puts[0]["oi"]      if top_puts  else 0,
            "gamma_wall":    gamma_wall,
            "top_call_walls": top_calls,
            "top_put_walls":  top_puts,
        }

    @staticmethod
    def detect_oi_support_resistance(
        chain: dict,
        expiry: str | None = None,
        top_n: int = _TOP_N,
    ) -> dict:
        """Put OI concentration → support levels; call OI → resistance levels."""
        rows = _strikes_for_expiry(chain, expiry)
        spot = _underlying(chain) or 0.0

        call_rows: list[dict] = []
        put_rows: list[dict] = []
        for r in rows:
            sp = r.get("strikePrice")
            ce = r.get("CE") or {}
            pe = r.get("PE") or {}
            if ce and sp:
                call_rows.append({"level": sp, "call_oi": ce.get("openInterest", 0) or 0})
            if pe and sp:
                put_rows.append({"level": sp, "put_oi": pe.get("openInterest", 0) or 0})

        top_calls = sorted(call_rows, key=lambda x: x["call_oi"], reverse=True)[:top_n]
        top_puts  = sorted(put_rows,  key=lambda x: x["put_oi"],  reverse=True)[:top_n]

        max_call_oi = top_calls[0]["call_oi"] if top_calls else 1
        max_put_oi  = top_puts[0]["put_oi"]   if top_puts  else 1

        resistances = [
            {
                "level": r["level"],
                "call_oi": r["call_oi"],
                "strength": _oi_strength(r["call_oi"], max_call_oi),
            }
            for r in top_calls
        ]
        supports = [
            {
                "level": r["level"],
                "put_oi": r["put_oi"],
                "strength": _oi_strength(r["put_oi"], max_put_oi),
            }
            for r in top_puts
        ]

        return {"supports": supports, "resistances": resistances}

    @staticmethod
    def detect_oi_buildup(chain: dict, expiry: str | None = None) -> dict:
        """Classify each strike's OI change pattern.

        Long buildup:    price above ATM + OI up  (call buying pressure)
        Short buildup:   price below ATM + OI up  (put writing pressure)
        Long unwinding:  OI down + ITM calls
        Short covering:  OI down + ITM puts
        """
        rows = _strikes_for_expiry(chain, expiry)
        spot = _underlying(chain) or 0.0

        call_buildup: list[dict] = []
        put_buildup: list[dict] = []
        unwinding: list[dict] = []

        for r in rows:
            sp = r.get("strikePrice") or 0.0
            ce = r.get("CE") or {}
            pe = r.get("PE") or {}

            ce_oi_change = ce.get("changeinOpenInterest", 0) or 0
            pe_oi_change = pe.get("changeinOpenInterest", 0) or 0

            if ce and abs(ce_oi_change) > _OI_CHANGE_MIN:
                ltp = ce.get("lastPrice") or 0
                entry: dict = {
                    "strike": sp,
                    "oi": ce.get("openInterest", 0) or 0,
                    "change_oi": ce_oi_change,
                    "type": "CE",
                }
                if ce_oi_change > 0 and sp > spot:
                    entry["signal"] = "call_buildup"
                    call_buildup.append(entry)
                elif ce_oi_change < 0 and sp < spot:
                    entry["signal"] = "call_unwinding"
                    unwinding.append(entry)

            if pe and abs(pe_oi_change) > _OI_CHANGE_MIN:
                entry = {
                    "strike": sp,
                    "oi": pe.get("openInterest", 0) or 0,
                    "change_oi": pe_oi_change,
                    "type": "PE",
                }
                if pe_oi_change > 0 and sp < spot:
                    entry["signal"] = "put_buildup"
                    put_buildup.append(entry)
                elif pe_oi_change < 0 and sp > spot:
                    entry["signal"] = "put_unwinding"
                    unwinding.append(entry)

        # Sort by absolute OI change magnitude, keep top 5
        call_buildup.sort(key=lambda x: abs(x["change_oi"]), reverse=True)
        put_buildup.sort(key=lambda x: abs(x["change_oi"]), reverse=True)
        unwinding.sort(key=lambda x: abs(x["change_oi"]), reverse=True)

        return {
            "call_buildup": call_buildup[:5],
            "put_buildup":  put_buildup[:5],
            "unwinding":    unwinding[:5],
        }
