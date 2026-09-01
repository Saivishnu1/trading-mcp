from mcp.server.fastmcp import FastMCP

from src import meta as _meta
from src.analysis import regime

# Synthetic conviction fields deleted in Phase 22F (Commit 6).
# No longer present in any tool output — fully removed, not just deprecated.
_SETUP_FIELDS_TO_DELETE = {"confidence", "signal", "trade_quality", "quality", "bullish_probability"}


def _build_market_structure(raw: dict) -> dict:
    """
    Convert raw detect_market_regime service output to market_structure descriptor format.

    Phase 22F: replaces regime/confidence synthetic fields with observed boolean
    facts and an auto-generated descriptor array that always mirrors the booleans.
    """
    if "error" in raw:
        return raw

    price = raw.get("price") or 0.0
    ema20 = raw.get("ema20") or 0.0
    ema50 = raw.get("ema50") or 0.0
    adx = raw.get("adx") or 0.0
    rsi = raw.get("rsi") or 0.0

    price_above_ema20 = bool(price > ema20)
    ema20_above_ema50 = bool(ema20 > ema50)
    adx_above_25 = bool(adx > 25)
    rsi_above_60 = bool(rsi > 60)

    # Descriptor must always mirror booleans exactly — never hardcoded.
    descriptor = []
    if price_above_ema20:
        descriptor.append("price_above_ema20")
    if ema20_above_ema50:
        descriptor.append("ema20_above_ema50")
    if adx_above_25:
        descriptor.append("adx_above_25")
    if rsi_above_60:
        descriptor.append("rsi_above_60")

    if adx < 15:
        adx_note = "trend_absent"
    elif adx < 25:
        adx_note = "trend_weak"
    elif adx < 35:
        adx_note = "trend_present"
    else:
        adx_note = "strong_trend_present"

    if rsi < 30:
        rsi_note = "oversold"
    elif rsi < 45:
        rsi_note = "momentum_low"
    elif rsi < 55:
        rsi_note = "momentum_neutral"
    elif rsi < 70:
        rsi_note = "momentum_elevated"
    else:
        rsi_note = "overbought"

    return {
        "symbol": raw.get("symbol"),
        "market_structure": {
            "price": price,
            "ema20": ema20,
            "ema50": ema50,
            "adx": adx,
            "rsi": rsi,
            "price_above_ema20": price_above_ema20,
            "ema20_above_ema50": ema20_above_ema50,
            "adx_above_25": adx_above_25,
            "rsi_above_60": rsi_above_60,
            "descriptor": descriptor,
            "indicator_interpretation": {
                "type": "INTERPRETATION",
                "validation_status": "UNVALIDATED",
                "adx_note": adx_note,
                "rsi_note": rsi_note,
            },
        },
        # TODO Phase 23: remove _migration block from output
        # Keep only meta["schema_version"] going forward
        # _migration is temporary compatibility signal only
        "_migration": {
            "regime_removed": True,
            "replacement": "market_structure",
            "schema_version": 5,
        },
    }


def _generate_reasoning(
    price: float,
    ema20: float,
    ema50: float,
    adx: float,
    rsi: float,
    price_above_ema20: bool,
    ema20_above_ema50: bool,
    adx_above_25: bool,
    rsi_above_60: bool,
    adx_note: str,
    rsi_note: str,
    descriptor: list,
) -> list:
    # REASONING GENERATION RULES
    #
    # Reasoning MAY:
    # - describe current observed state
    # - summarize indicator values
    # - explain threshold crossings
    # - reference market_structure descriptors
    #
    # Reasoning MAY NOT:
    # - predict future price movement
    # - recommend a direction
    # - imply probability of success
    # - imply edge or conviction
    # - use synonyms for the above
    #
    # Test: could this sentence appear in a physics
    # textbook describing current state?
    # If yes → allowed.
    # If it implies what will happen next → forbidden.
    reasoning = []

    # Price vs EMA20 — observed fact
    if price_above_ema20:
        reasoning.append(f"Price ({price}) is above EMA20 ({ema20:.2f}).")
    else:
        reasoning.append(f"Price ({price}) is below EMA20 ({ema20:.2f}).")

    # EMA20 vs EMA50 — observed fact
    if ema20_above_ema50:
        reasoning.append(f"EMA20 ({ema20:.2f}) is above EMA50 ({ema50:.2f}).")
    else:
        reasoning.append(f"EMA20 ({ema20:.2f}) is below EMA50 ({ema50:.2f}).")

    # ADX — threshold crossing + note only
    reasoning.append(
        f"ADX is {adx:.2f} "
        f"({'above' if adx_above_25 else 'below'} the 25 threshold): {adx_note}."
    )

    # RSI — classification only
    reasoning.append(f"RSI is {rsi:.2f}: {rsi_note}.")

    # Descriptor summary — current structure, no interpretation
    if descriptor:
        reasoning.append(
            f"Current market structure includes: {', '.join(descriptor)}."
        )
    else:
        reasoning.append("No threshold conditions currently met.")

    return reasoning


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def calculate_risk_reward(entry: float, stoploss: float, target: float) -> dict:
        """Calculate absolute risk, reward, and reward-to-risk ratio.

        Args:
            entry: Proposed trade entry price.
            stoploss: Protective stop price.
            target: Profit target price.
        """
        data = regime.calculate_risk_reward(entry, stoploss, target)
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_COMPUTED,
            data_quality=_meta.DQ_VALID,
            source="internal_journal",
            account_type="MARKET_DATA_ONLY",
        )
        return _meta.wrap(data, m)

    @mcp.tool()
    def calculate_position_size(
        capital: float,
        risk_percent: float,
        entry: float,
        stoploss: float,
    ) -> dict:
        """Calculate position size from capital, risk %, entry, and stoploss.

        Args:
            capital: Total trading capital.
            risk_percent: Percent of capital to risk on the trade.
            entry: Planned entry price.
            stoploss: Planned stoploss price.
        """
        data = regime.calculate_position_size(capital, risk_percent, entry, stoploss)
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_COMPUTED,
            data_quality=_meta.DQ_VALID,
            source="internal_journal",
            account_type="MARKET_DATA_ONLY",
        )
        return _meta.wrap(data, m)
