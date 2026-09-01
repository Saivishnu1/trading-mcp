"""
IV analytics — ATM IV, skew, and term-structure surface.

Works on the raw NSE/BSE chain dict (records.data format).
"""
from __future__ import annotations

from src.options.analytics import _strikes_for_expiry, _underlying


class IVAnalyzer:

    @staticmethod
    def get_iv_surface(chain: dict, expiry: str | None = None) -> dict:
        """Return ATM IV, IV skew (put vs call), and available term-structure IVs."""
        rows = _strikes_for_expiry(chain, expiry)
        spot = _underlying(chain) or 0.0

        all_strikes: list[float] = sorted({
            float(r["strikePrice"]) for r in rows if r.get("strikePrice") is not None
        })
        if not all_strikes or spot <= 0:
            return {
                "atm_iv": None,
                "atm_strike": None,
                "put_iv": None,
                "call_iv": None,
                "iv_skew": None,
                "skew_interpretation": "insufficient data",
                "term_structure": [],
            }

        atm_strike = min(all_strikes, key=lambda s: abs(s - spot))

        # ATM row IV
        atm_ce_iv = atm_pe_iv = None
        for r in rows:
            if r.get("strikePrice") == atm_strike:
                ce = r.get("CE") or {}
                pe = r.get("PE") or {}
                atm_ce_iv = ce.get("impliedVolatility")
                atm_pe_iv = pe.get("impliedVolatility")
                break

        atm_iv = None
        if atm_ce_iv is not None and atm_pe_iv is not None:
            atm_iv = round((atm_ce_iv + atm_pe_iv) / 2, 2)
        elif atm_ce_iv is not None:
            atm_iv = round(atm_ce_iv, 2)
        elif atm_pe_iv is not None:
            atm_iv = round(atm_pe_iv, 2)

        # Skew: average OTM put IV vs average OTM call IV
        otm_put_ivs: list[float] = []
        otm_call_ivs: list[float] = []
        for r in rows:
            sp = r.get("strikePrice") or 0.0
            ce = r.get("CE") or {}
            pe = r.get("PE") or {}
            if sp < spot and pe.get("impliedVolatility"):
                otm_put_ivs.append(float(pe["impliedVolatility"]))
            if sp > spot and ce.get("impliedVolatility"):
                otm_call_ivs.append(float(ce["impliedVolatility"]))

        avg_put_iv  = round(sum(otm_put_ivs)  / len(otm_put_ivs),  2) if otm_put_ivs  else None
        avg_call_iv = round(sum(otm_call_ivs) / len(otm_call_ivs), 2) if otm_call_ivs else None

        iv_skew = None
        if avg_put_iv is not None and avg_call_iv is not None and avg_call_iv > 0:
            iv_skew = round(avg_put_iv - avg_call_iv, 2)

        skew_interp = IVAnalyzer._skew_interpretation(iv_skew)

        # Term structure: collect ATM IV for each available expiry using all rows
        all_rows_all_expiries: list[dict] = chain.get("records", {}).get("data", [])
        term: dict[str, list[float]] = {}
        for r in all_rows_all_expiries:
            exp = r.get("expiryDate") or ""
            sp = r.get("strikePrice") or 0.0
            ce = r.get("CE") or {}
            pe = r.get("PE") or {}
            iv_ce = ce.get("impliedVolatility")
            iv_pe = pe.get("impliedVolatility")
            if exp and sp == atm_strike:
                for iv in filter(None, [iv_ce, iv_pe]):
                    term.setdefault(exp, []).append(float(iv))

        term_structure = [
            {"expiry": exp, "atm_iv": round(sum(ivs) / len(ivs), 2)}
            for exp, ivs in sorted(term.items())
            if ivs
        ]

        return {
            "atm_iv":            atm_iv,
            "atm_strike":        atm_strike,
            "put_iv":            avg_put_iv,
            "call_iv":           avg_call_iv,
            "iv_skew":           iv_skew,
            "skew_interpretation": skew_interp,
            "term_structure":    term_structure,
        }

    @staticmethod
    def _skew_interpretation(iv_skew: float | None) -> str:
        if iv_skew is None:
            return "insufficient data"
        if iv_skew > 3.0:
            return "Put skew elevated — hedging demand visible"
        if iv_skew > 1.0:
            return "Mild put skew — moderate downside hedging"
        if iv_skew < -3.0:
            return "Call skew elevated — upside demand visible"
        if iv_skew < -1.0:
            return "Mild call skew — moderate upside demand"
        return "IV skew near flat — balanced put/call premium"

    @staticmethod
    def get_atm_iv_interpretation(atm_iv: float | None) -> str:
        if atm_iv is None:
            return "ATM IV unavailable"
        if atm_iv < 10:
            return f"ATM IV {atm_iv:.1f} — very low premium environment"
        if atm_iv < 15:
            return f"ATM IV {atm_iv:.1f} — low premium environment"
        if atm_iv < 20:
            return f"ATM IV {atm_iv:.1f} — moderate premium environment"
        if atm_iv < 30:
            return f"ATM IV {atm_iv:.1f} — elevated premium environment"
        return f"ATM IV {atm_iv:.1f} — high premium environment, elevated uncertainty"
