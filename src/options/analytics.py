"""
Pure analytics functions over NSE option chain data.

All functions accept the raw dict returned by OptionsService.get_option_chain()
and an optional *expiry* string. No I/O is performed here.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strikes_for_expiry(chain_data: dict, expiry: str | None) -> list[dict]:
    """Return the data[] rows for a given expiry (or all expiries if None)."""
    data: list[dict] = chain_data.get("records", {}).get("data", [])
    if expiry:
        data = [d for d in data if d.get("expiryDate") == expiry]
    return data


def _underlying(chain_data: dict) -> float | None:
    return chain_data.get("records", {}).get("underlyingValue")


# ---------------------------------------------------------------------------
# PCR
# ---------------------------------------------------------------------------

def calculate_pcr(chain_data: dict, expiry: str | None = None) -> dict:
    """Put-Call Ratio by open interest and by volume.

    PCR (OI) > 1.3  →  broadly bullish sentiment
    PCR (OI) < 0.7  →  broadly bearish sentiment
    """
    rows = _strikes_for_expiry(chain_data, expiry)

    total_call_oi  = sum(r.get("CE", {}).get("openInterest", 0) for r in rows)
    total_put_oi   = sum(r.get("PE", {}).get("openInterest", 0) for r in rows)
    total_call_vol = sum(r.get("CE", {}).get("totalTradedVolume", 0) for r in rows)
    total_put_vol  = sum(r.get("PE", {}).get("totalTradedVolume", 0) for r in rows)

    pcr_oi  = round(total_put_oi  / total_call_oi,  4) if total_call_oi  else None
    pcr_vol = round(total_put_vol / total_call_vol, 4) if total_call_vol else None

    return {
        "expiry": expiry or "all",
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "pcr_oi": pcr_oi,
        "total_call_volume": total_call_vol,
        "total_put_volume": total_put_vol,
        "pcr_volume": pcr_vol,
        "interpretation": _pcr_sentiment(pcr_oi),
    }


def _pcr_sentiment(pcr: float | None) -> str:
    if pcr is None:
        return "insufficient data"
    if pcr > 1.3:
        return "bullish — elevated put writing signals market expects upside"
    if pcr > 1.0:
        return "mildly bullish"
    if pcr > 0.7:
        return "neutral to mildly bearish"
    return "bearish — elevated call writing signals market expects downside"


# ---------------------------------------------------------------------------
# OI analysis
# ---------------------------------------------------------------------------

def get_oi_analysis(
    chain_data: dict,
    expiry: str | None = None,
    top_n: int = 10,
) -> dict:
    """Return the top-OI call and put strikes with volume and IV."""
    rows = _strikes_for_expiry(chain_data, expiry)
    spot = _underlying(chain_data)

    call_rows: list[dict] = []
    put_rows:  list[dict] = []

    for r in rows:
        sp = r.get("strikePrice")
        ce = r.get("CE") or {}
        pe = r.get("PE") or {}
        if ce:
            call_rows.append({
                "strike":     sp,
                "oi":         ce.get("openInterest", 0),
                "change_oi":  ce.get("changeinOpenInterest", 0),
                "volume":     ce.get("totalTradedVolume", 0),
                "iv":         ce.get("impliedVolatility"),
                "ltp":        ce.get("lastPrice"),
            })
        if pe:
            put_rows.append({
                "strike":     sp,
                "oi":         pe.get("openInterest", 0),
                "change_oi":  pe.get("changeinOpenInterest", 0),
                "volume":     pe.get("totalTradedVolume", 0),
                "iv":         pe.get("impliedVolatility"),
                "ltp":        pe.get("lastPrice"),
            })

    top_calls = sorted(call_rows, key=lambda x: x["oi"], reverse=True)[:top_n]
    top_puts  = sorted(put_rows,  key=lambda x: x["oi"], reverse=True)[:top_n]

    return {
        "underlying_value":      spot,
        "expiry":                expiry or "all",
        "top_call_oi_strikes":   top_calls,
        "top_put_oi_strikes":    top_puts,
        "max_call_oi_strike":    top_calls[0]["strike"] if top_calls else None,
        "max_put_oi_strike":     top_puts[0]["strike"]  if top_puts  else None,
    }


# ---------------------------------------------------------------------------
# Support / Resistance from OI
# ---------------------------------------------------------------------------

def identify_support_resistance_from_oi(
    chain_data: dict,
    expiry: str | None = None,
    top_n: int = 5,
) -> dict:
    """Derive support and resistance zones from OI concentration.

    Resistance: strikes with the highest call OI — option writers defend these.
    Support:    strikes with the highest put  OI — option writers defend these.
    """
    analysis = get_oi_analysis(chain_data, expiry, top_n)
    spot = analysis["underlying_value"] or 0.0

    resistance = [
        {"strike": s["strike"], "oi": s["oi"], "basis": "high call OI"}
        for s in analysis["top_call_oi_strikes"]
    ]
    support = [
        {"strike": s["strike"], "oi": s["oi"], "basis": "high put OI"}
        for s in analysis["top_put_oi_strikes"]
    ]

    nearest_resistance = min(
        (s for s in resistance if s["strike"] > spot),
        key=lambda x: x["strike"],
        default=None,
    )
    nearest_support = max(
        (s for s in support if s["strike"] < spot),
        key=lambda x: x["strike"],
        default=None,
    )

    return {
        "underlying_value":   spot or None,
        "expiry":             expiry or "all",
        "resistance_levels":  resistance,
        "support_levels":     support,
        "nearest_resistance": nearest_resistance,
        "nearest_support":    nearest_support,
    }


# ---------------------------------------------------------------------------
# Max Pain
# ---------------------------------------------------------------------------

def calculate_max_pain(chain_data: dict, expiry: str | None = None) -> dict:
    """Max pain strike: the expiry level at which total ITM option value is minimised.

    At max pain, option buyers have the maximum aggregate loss — historically
    the underlying tends to gravitate toward this level into expiry.

    Algorithm:
      For each candidate strike S:
        call_pain(S) = Σ max(S − K, 0) × call_OI(K)   for all K
        put_pain(S)  = Σ max(K − S, 0) × put_OI(K)    for all K
        total_pain(S) = call_pain(S) + put_pain(S)
      Max pain = S where total_pain(S) is minimised.
    """
    rows   = _strikes_for_expiry(chain_data, expiry)
    spot   = _underlying(chain_data)

    call_oi: dict[float, int] = {}
    put_oi:  dict[float, int] = {}

    for r in rows:
        sp = float(r.get("strikePrice", 0))
        ce = r.get("CE") or {}
        pe = r.get("PE") or {}
        if ce:
            call_oi[sp] = ce.get("openInterest", 0)
        if pe:
            put_oi[sp] = pe.get("openInterest", 0)

    all_strikes = sorted(set(call_oi) | set(put_oi))
    if not all_strikes:
        return {"max_pain": None, "expiry": expiry or "all", "underlying_value": spot}

    pain: dict[float, float] = {}
    for candidate in all_strikes:
        c_pain = sum(max(0.0, candidate - sp) * call_oi.get(sp, 0) for sp in all_strikes)
        p_pain = sum(max(0.0, sp - candidate) * put_oi.get(sp, 0)  for sp in all_strikes)
        pain[candidate] = c_pain + p_pain

    max_pain_strike = min(pain, key=pain.__getitem__)

    pain_table = sorted(
        [{"strike": k, "total_pain": round(v)} for k, v in pain.items()],
        key=lambda x: x["total_pain"],
    )

    return {
        "max_pain":               max_pain_strike,
        "underlying_value":       spot,
        "expiry":                 expiry or "all",
        "distance_from_spot":     round(spot - max_pain_strike, 2) if spot else None,
        "pain_table_top20":       pain_table[:20],
    }
