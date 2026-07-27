"""
Option Strategy Builder — Phase 6.

Converts a trade plan into a concrete options structure with specific
strikes, expiry, and real payoff calculations when premium data is available.

Read-only: no orders placed, no Zerodha order API called.

Reuses:
  detect_market_regime()   → spot price
  recommend_strategy()     → strategy name + signal
  create_trade_plan()      → trade_quality
  OptionsService           → live chain (NIFTY/BANKNIFTY index only)
  analytics                → S/R zones for Iron Condor leg selection
"""

from __future__ import annotations

import logging
from collections import Counter

from src.analysis.regime import detect_market_regime, recommend_strategy
from src.options import analytics
from src.options.service import get_options_service
from src.planner.trade_plan import create_trade_plan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strike helpers
# ---------------------------------------------------------------------------

def _sorted_strikes(chain_data: dict, expiry: str) -> list[float]:
    rows = chain_data.get("records", {}).get("data", [])
    return sorted({
        float(r["strikePrice"])
        for r in rows
        if r.get("expiryDate") == expiry and "strikePrice" in r
    })


def _interval(strikes: list[float]) -> float:
    if len(strikes) < 2:
        return 50.0
    diffs = [round(strikes[i + 1] - strikes[i]) for i in range(len(strikes) - 1)]
    return float(Counter(diffs).most_common(1)[0][0])


def _nearest(strikes: list[float], target: float) -> float:
    return min(strikes, key=lambda s: abs(s - target))


def _atm(strikes: list[float], spot: float) -> float:
    return _nearest(strikes, spot)


def _atm_ce(strikes: list[float], spot: float) -> float:
    """First strike at or above spot (ATM or first ITM CE)."""
    above = [s for s in strikes if s >= spot]
    return min(above) if above else strikes[-1]


def _atm_pe(strikes: list[float], spot: float) -> float:
    """First strike at or below spot (ATM or first ITM PE)."""
    below = [s for s in strikes if s <= spot]
    return max(below) if below else strikes[0]


# ---------------------------------------------------------------------------
# Premium lookup
# ---------------------------------------------------------------------------

def _build_pmap(chain_data: dict, expiry: str) -> dict[tuple[float, str], float]:
    """Map (strike, option_type) → last traded premium for the given expiry."""
    pmap: dict[tuple[float, str], float] = {}
    for row in chain_data.get("records", {}).get("data", []):
        if row.get("expiryDate") != expiry:
            continue
        strike = float(row.get("strikePrice", 0))
        for otype in ("CE", "PE"):
            leg_data = row.get(otype)
            if not leg_data:
                continue
            # NSE chain uses "lastPrice"; analytics output calls it "ltp"
            raw = leg_data.get("lastPrice") or leg_data.get("ltp") or 0
            price = float(raw)
            if price > 0:
                pmap[(strike, otype)] = price
    return pmap


def _ltp(pmap: dict, strike: float, otype: str) -> float | None:
    return pmap.get((strike, otype))


# Audit-H4: strikes with a wide bid-ask spread or thin open interest can have
# a `lastPrice` that is a stale, unrepresentative print from a much earlier
# trade — the reported max_loss/net_credit is not what a real order would
# actually fill at. Flag rather than silently trust `lastPrice` alone.
_WIDE_SPREAD_PCT_THRESHOLD = 10.0   # spread as % of mid-price
_LOW_OI_THRESHOLD = 500              # open interest floor


def _build_liquidity_map(chain_data: dict, expiry: str) -> dict[tuple[float, str], dict]:
    """Map (strike, option_type) → {bid, ask, oi} for the given expiry."""
    liq: dict[tuple[float, str], dict] = {}
    for row in chain_data.get("records", {}).get("data", []):
        if row.get("expiryDate") != expiry:
            continue
        strike = float(row.get("strikePrice", 0))
        for otype in ("CE", "PE"):
            leg_data = row.get(otype)
            if not leg_data:
                continue
            liq[(strike, otype)] = {
                "bid": leg_data.get("bidprice"),
                "ask": leg_data.get("askPrice"),
                "oi": leg_data.get("openInterest"),
            }
    return liq


def _leg_liquidity_warning(strike: float, otype: str, liquidity_map: dict) -> str | None:
    """Return a warning string if this leg's spread is wide or OI is thin;
    None if the leg looks liquid or liquidity data is unavailable (never
    fabricates a warning from absent data)."""
    info = liquidity_map.get((strike, otype))
    if not info:
        return None
    bid, ask, oi = info.get("bid"), info.get("ask"), info.get("oi")
    warnings = []
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / 2
        if mid > 0:
            spread_pct = (ask - bid) / mid * 100
            if spread_pct > _WIDE_SPREAD_PCT_THRESHOLD:
                warnings.append(f"spread {spread_pct:.0f}% of mid")
    if oi is not None and oi < _LOW_OI_THRESHOLD:
        warnings.append(f"OI only {int(oi)}")
    if not warnings:
        return None
    return f"{int(strike)}{otype}: " + ", ".join(warnings)


# ---------------------------------------------------------------------------
# Leg selection
# ---------------------------------------------------------------------------

def _select_legs(
    strategy: str,
    spot: float,
    strikes: list[float],
    ivl: float,
    chain_data: dict,
    expiry: str,
) -> list[dict]:
    atm_strike    = _atm(strikes, spot)
    atm_ce_strike = _atm_ce(strikes, spot)
    atm_pe_strike = _atm_pe(strikes, spot)
    spread_width  = ivl * 4  # 4-interval spread for directional spreads

    if strategy == "Long Call":
        return [{"action": "BUY", "strike": atm_ce_strike, "option_type": "CE"}]

    if strategy == "Long Put":
        return [{"action": "BUY", "strike": atm_pe_strike, "option_type": "PE"}]

    if strategy == "Bull Call Spread":
        short_ce = _nearest(strikes, atm_ce_strike + spread_width)
        return [
            {"action": "BUY",  "strike": atm_ce_strike, "option_type": "CE"},
            {"action": "SELL", "strike": short_ce,       "option_type": "CE"},
        ]

    if strategy == "Bear Put Spread":
        short_pe = _nearest(strikes, atm_pe_strike - spread_width)
        return [
            {"action": "BUY",  "strike": atm_pe_strike, "option_type": "PE"},
            {"action": "SELL", "strike": short_pe,       "option_type": "PE"},
        ]

    if strategy == "Long Straddle":
        return [
            {"action": "BUY", "strike": atm_strike, "option_type": "CE"},
            {"action": "BUY", "strike": atm_strike, "option_type": "PE"},
        ]

    if strategy == "Long Strangle":
        otm_ce = _nearest(strikes, atm_strike + ivl * 2)
        otm_pe = _nearest(strikes, atm_strike - ivl * 2)
        return [
            {"action": "BUY", "strike": otm_ce, "option_type": "CE"},
            {"action": "BUY", "strike": otm_pe, "option_type": "PE"},
        ]

    if strategy == "Iron Condor":
        # Default short legs: ATM ± 2 intervals; override with OI-based S/R when available
        short_ce_strike = _nearest(strikes, atm_strike + ivl * 2)
        short_pe_strike = _nearest(strikes, atm_strike - ivl * 2)
        try:
            sr = analytics.identify_support_resistance_from_oi(chain_data, expiry, top_n=5)
            nr = (sr.get("nearest_resistance") or {}).get("strike")
            ns = (sr.get("nearest_support")    or {}).get("strike")
            if nr and nr in strikes:
                short_ce_strike = nr
            if ns and ns in strikes:
                short_pe_strike = ns
        except Exception:
            pass  # keep ATM-interval fallback
        long_ce = _nearest(strikes, short_ce_strike + spread_width)
        long_pe = _nearest(strikes, short_pe_strike - spread_width)
        return [
            {"action": "SELL", "strike": short_ce_strike, "option_type": "CE"},
            {"action": "BUY",  "strike": long_ce,          "option_type": "CE"},
            {"action": "SELL", "strike": short_pe_strike,  "option_type": "PE"},
            {"action": "BUY",  "strike": long_pe,          "option_type": "PE"},
        ]

    return []


# ---------------------------------------------------------------------------
# Payoff calculations
# ---------------------------------------------------------------------------

def _calc_payoff(strategy: str, legs: list[dict], pmap: dict) -> dict:
    """
    Calculate max_loss, max_profit, and breakeven(s) from real premiums.

    Returns is_estimate=False when real LTPs are used.
    Returns is_estimate=True when any premium is missing — caller should
    surface this to the user.
    """
    def p(strike: float, otype: str) -> float | None:
        return pmap.get((strike, otype))

    def missing(*vals) -> bool:
        return any(v is None for v in vals)

    if strategy == "Bull Call Spread":
        buy_strike, sell_strike = legs[0]["strike"], legs[1]["strike"]
        buy_p, sell_p = p(buy_strike, "CE"), p(sell_strike, "CE")
        if missing(buy_p, sell_p):
            return {"is_estimate": True}
        net_debit  = round(buy_p - sell_p, 2)
        spread_w   = sell_strike - buy_strike
        return {
            "is_estimate":    False,
            "net_debit":      net_debit,
            "estimated_cost": net_debit,
            "max_loss":       net_debit,
            "max_profit":     round(spread_w - net_debit, 2),
            "upper_breakeven": round(buy_strike + net_debit, 2),
            "lower_breakeven": round(buy_strike + net_debit, 2),
        }

    if strategy == "Bear Put Spread":
        buy_strike, sell_strike = legs[0]["strike"], legs[1]["strike"]
        buy_p, sell_p = p(buy_strike, "PE"), p(sell_strike, "PE")
        if missing(buy_p, sell_p):
            return {"is_estimate": True}
        net_debit = round(buy_p - sell_p, 2)
        spread_w  = buy_strike - sell_strike
        be        = round(buy_strike - net_debit, 2)
        return {
            "is_estimate":     False,
            "net_debit":       net_debit,
            "estimated_cost":  net_debit,
            "max_loss":        net_debit,
            "max_profit":      round(spread_w - net_debit, 2),
            "upper_breakeven": be,
            "lower_breakeven": be,
        }

    if strategy == "Long Call":
        strike = legs[0]["strike"]
        buy_p = p(strike, "CE")
        if buy_p is None:
            return {"is_estimate": True}
        be = round(strike + buy_p, 2)
        return {
            "is_estimate":     False,
            "estimated_cost":  round(buy_p, 2),
            "max_loss":        round(buy_p, 2),
            "max_profit":      "unlimited",
            "upper_breakeven": be,
            "lower_breakeven": be,
        }

    if strategy == "Long Put":
        strike = legs[0]["strike"]
        buy_p = p(strike, "PE")
        if buy_p is None:
            return {"is_estimate": True}
        be = round(strike - buy_p, 2)
        return {
            "is_estimate":     False,
            "estimated_cost":  round(buy_p, 2),
            "max_loss":        round(buy_p, 2),
            "max_profit":      round(strike - buy_p, 2),
            "upper_breakeven": be,
            "lower_breakeven": be,
        }

    if strategy == "Long Straddle":
        strike = legs[0]["strike"]
        cp, pp  = p(strike, "CE"), p(strike, "PE")
        if missing(cp, pp):
            return {"is_estimate": True}
        total = round(cp + pp, 2)
        return {
            "is_estimate":     False,
            "estimated_cost":  total,
            "max_loss":        total,
            "max_profit":      "unlimited",
            "upper_breakeven": round(strike + total, 2),
            "lower_breakeven": round(strike - total, 2),
        }

    if strategy == "Long Strangle":
        ce_strike, pe_strike = legs[0]["strike"], legs[1]["strike"]
        cp, pp = p(ce_strike, "CE"), p(pe_strike, "PE")
        if missing(cp, pp):
            return {"is_estimate": True}
        total = round(cp + pp, 2)
        return {
            "is_estimate":     False,
            "estimated_cost":  total,
            "max_loss":        total,
            "max_profit":      "unlimited",
            "upper_breakeven": round(ce_strike + total, 2),
            "lower_breakeven": round(pe_strike - total, 2),
        }

    if strategy == "Iron Condor":
        # legs: [SELL CE, BUY CE, SELL PE, BUY PE]
        sc, lc = legs[0]["strike"], legs[1]["strike"]
        sp, lp = legs[2]["strike"], legs[3]["strike"]
        sc_p, lc_p = p(sc, "CE"), p(lc, "CE")
        sp_p, lp_p = p(sp, "PE"), p(lp, "PE")
        if missing(sc_p, lc_p, sp_p, lp_p):
            return {"is_estimate": True}
        net_credit   = round((sc_p - lc_p) + (sp_p - lp_p), 2)
        call_width   = lc - sc
        put_width    = sp - lp
        max_risk     = max(call_width, put_width)
        return {
            "is_estimate":     False,
            "net_credit":      net_credit,
            "estimated_cost":  round(-net_credit, 2),   # negative = credit received
            "max_loss":        round(max_risk - net_credit, 2),
            "max_profit":      net_credit,
            "upper_breakeven": round(sc + net_credit, 2),
            "lower_breakeven": round(sp - net_credit, 2),
        }

    return {"is_estimate": True}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _build_summary(
    strategy: str,
    signal: str,
    legs: list[dict],
    payoff: dict,
    sym: str,
    liquidity_warnings: list[str] | None = None,
) -> str:
    if not legs:
        return (
            f"{strategy} identified for {sym}, but option chain data is unavailable "
            "for this symbol. Use your broker terminal to select strikes near spot."
        )

    leg_desc = ", ".join(
        f"{l['action']} {int(l['strike'])} {l['option_type']}" for l in legs
    )

    liquidity_suffix = ""
    if liquidity_warnings:
        liquidity_suffix = (
            " Liquidity caution — lastPrice may not be fillable near the reported "
            f"level for: {'; '.join(liquidity_warnings)}."
        )

    if payoff.get("is_estimate"):
        if liquidity_warnings:
            return (
                f"{strategy} selected for {sym} based on {signal} signal. "
                f"Legs: {leg_desc}. Real premiums were found but at least one leg "
                "has a wide bid-ask spread or thin open interest, so the reported "
                f"numbers may not be fillable at those levels.{liquidity_suffix}"
            )
        return (
            f"{strategy} selected for {sym} based on {signal} signal. "
            f"Legs: {leg_desc}. "
            "Premium data unavailable — max loss/profit require live option prices."
        )

    max_loss   = payoff.get("max_loss", "N/A")
    max_profit = payoff.get("max_profit", "N/A")
    ube        = payoff.get("upper_breakeven", "N/A")
    lbe        = payoff.get("lower_breakeven")

    be_str = (
        f"Breakeven: {ube} / {lbe}"
        if lbe is not None and lbe != ube
        else f"Breakeven: {ube}"
    )

    return (
        f"{strategy} selected for {sym} based on {signal} signal. "
        f"Legs: {leg_desc}. "
        f"Max loss: {max_loss} | Max profit: {max_profit}. {be_str}.{liquidity_suffix}"
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_option_strategy(symbol: str, expiry: str | None = None) -> dict:
    """
    Build a concrete options strategy for *symbol*.

    Does NOT place orders or call the Zerodha order API.
    All output is for planning and review only.
    """
    sym = symbol.upper()

    # --- Core analysis (reuse existing modules) ---
    regime_result = detect_market_regime(symbol)
    if "error" in regime_result:
        return {"symbol": sym, "error": regime_result["error"]}

    strat_result = recommend_strategy(symbol)
    if "error" in strat_result:
        return {"symbol": sym, "error": strat_result["error"]}

    plan = create_trade_plan(symbol)

    spot: float          = regime_result["price"]
    signal: str          = strat_result.get("signal", "")
    strategy_name: str   = strat_result.get("recommended", strat_result.get("strategy", ""))
    trade_quality: str | None = plan.get("trade_quality")

    # --- Option chain (index only; equities gracefully degrade) ---
    chain_data: dict | None = None
    chain_expiry: str | None = expiry
    pmap: dict = {}
    liquidity_map: dict = {}
    premium_data_available = False
    strikes: list[float] = []

    try:
        svc = get_options_service()
        chain_data = svc.get_option_chain(symbol)
        records = chain_data.get("records", {})

        # Live spot from chain is more accurate than last daily close
        chain_spot = records.get("underlyingValue")
        if chain_spot:
            spot = float(chain_spot)

        expiry_dates: list[str] = records.get("expiryDates", [])
        if not expiry_dates:
            raise ValueError("no expiry dates returned by chain")

        if chain_expiry is None:
            chain_expiry = expiry_dates[0]       # nearest expiry
        elif chain_expiry not in expiry_dates:
            logger.warning(
                "Requested expiry %s not in chain; falling back to nearest %s",
                chain_expiry, expiry_dates[0],
            )
            chain_expiry = expiry_dates[0]

        strikes = _sorted_strikes(chain_data, chain_expiry)
        pmap    = _build_pmap(chain_data, chain_expiry)
        liquidity_map = _build_liquidity_map(chain_data, chain_expiry)
        premium_data_available = bool(pmap)

    except Exception as exc:
        logger.debug("Option chain unavailable for %s: %s", symbol, exc)

    # --- Equity / no-chain path ---
    if not strikes:
        return {
            "symbol":                sym,
            "strategy":              strategy_name,
            "expiry":                chain_expiry,
            "spot_price":            round(spot, 2),
            "signal":                signal,
            "trade_quality":         trade_quality,
            "premium_data_available": False,
            "legs":                  [],
            "estimated_cost":        None,
            "max_loss":              None,
            "max_profit":            None,
            "upper_breakeven":       None,
            "lower_breakeven":       None,
            "is_estimate":           True,
            "summary": (
                f"{strategy_name} identified for {sym}, but option chain data is "
                "unavailable for this symbol. Use your broker terminal to select "
                "strikes near the current spot price."
            ),
        }

    # --- Strike selection & payoff ---
    ivl  = _interval(strikes)
    legs = _select_legs(strategy_name, spot, strikes, ivl, chain_data, chain_expiry)

    # Attach live premium to each leg (None when not in pmap)
    for leg in legs:
        leg["ltp"] = _ltp(pmap, leg["strike"], leg["option_type"])

    payoff = _calc_payoff(strategy_name, legs, pmap)

    leg_liquidity_warnings = [
        w for w in (
            _leg_liquidity_warning(leg["strike"], leg["option_type"], liquidity_map)
            for leg in legs
        ) if w
    ]
    if leg_liquidity_warnings:
        # A wide-spread/thin-OI leg's lastPrice may not be fillable near the
        # reported value — this qualifies is_estimate even when a premium
        # was found (Audit-H4).
        payoff = {**payoff, "is_estimate": True}

    return {
        "symbol":                sym,
        "strategy":              strategy_name,
        "expiry":                chain_expiry,
        "spot_price":            round(spot, 2),
        "signal":                signal,
        "trade_quality":         trade_quality,
        "premium_data_available": premium_data_available,
        "legs":                  legs,
        "estimated_cost":        payoff.get("estimated_cost"),
        "max_loss":              payoff.get("max_loss"),
        "max_profit":            payoff.get("max_profit"),
        "upper_breakeven":       payoff.get("upper_breakeven"),
        "lower_breakeven":       payoff.get("lower_breakeven"),
        "is_estimate":           payoff.get("is_estimate", True),
        "liquidity_warning":     "; ".join(leg_liquidity_warnings) if leg_liquidity_warnings else None,
        "summary":               _build_summary(strategy_name, signal, legs, payoff, sym, leg_liquidity_warnings),
    }
