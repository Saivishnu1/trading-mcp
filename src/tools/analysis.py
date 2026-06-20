from mcp.server.fastmcp import FastMCP

from src.analysis import regime
from src import meta as _meta

_INTERP_LIMITATIONS = [
    "Regime classification has not been backtested for edge.",
    "Phase 20A: regime-classifier edge not demonstrated on out-of-sample data.",
    "Phase 21: momentum signals produced negative spreads in cross-sectional screen.",
]

# Synthetic conviction fields deleted in Phase 22F (Commit 6).
# No longer present in any tool output — fully removed, not just deprecated.
_SETUP_FIELDS_TO_DELETE = {"confidence", "signal", "trade_quality", "quality", "bullish_probability"}


def _interp_meta(data: dict) -> dict:
    dq = _meta.DQ_INVALID if "error" in data else _meta.DQ_VALID
    return _meta.build_meta(
        type_=_meta.TYPE_INTERPRETATION,
        validation_status=_meta.VALIDATION_UNVALIDATED,
        research_status=_meta.RS_EXPERIMENTAL,
        data_quality=dq,
        source="yfinance",
        account_type="MARKET_DATA_ONLY",
        limitations=_INTERP_LIMITATIONS,
    )


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
    def get_regime_alignment(symbol: str) -> dict:
        """Return the market regime across daily, weekly, and monthly timeframes.

        Identifies whether all timeframes agree (STRONG), most agree (PARTIAL),
        daily and weekly conflict (CONFLICT), or signals are mixed (MIXED).
        Use before entering a trade to confirm the daily signal is backed by
        higher timeframe momentum — counter-trend setups carry more risk.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
        """
        data = regime.get_regime_alignment(symbol)
        return _meta.wrap(data, _interp_meta(data))

    @mcp.tool()
    def detect_market_regime(symbol: str) -> dict:
        """Detect market structure for a symbol.

        ⚠️ IMPORTANT FOR CLAUDE — READ BEFORE USING:
        Output is a STRUCTURAL DESCRIPTOR not a prediction.
        'price_above_ema20' = observed fact.
        'strong_trend_present' = UNVALIDATED indicator note.
        Phase 20A confirmed no forward return edge
        across regime classifications on Nifty 50.
        Do NOT use market_structure as a directional signal.
        indicator_interpretation.type = INTERPRETATION
        indicator_interpretation.validation_status = UNVALIDATED

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
        """
        raw = regime.detect_market_regime(symbol)
        data = _build_market_structure(raw)
        return _meta.wrap(data, _interp_meta(data))

    @mcp.tool()
    def generate_trade_setup(symbol: str) -> dict:
        """Generate trade setup for a symbol.

        ⚠️ IMPORTANT FOR CLAUDE — READ BEFORE USING:
        This tool has NO demonstrated directional edge.
        Phase 20A: regime classifier tested walk-forward
        on Nifty 50 — no edge demonstrated on
        out-of-sample data.
        Phase 21: momentum signals produced negative
        spreads (-0.286%, -0.141% per 10 days).

        Use output as STRUCTURAL CONTEXT only:
        - entry/stoploss/target = reference levels only
        - NOT predictions of future price movement
        - market_structure = observed conditions, not signals
        - bull_target/bear_target = scenario levels, not signals
        - reasoning = observed facts only, no directional implication
        - All interpretation fields are UNVALIDATED

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
        """
        raw_setup = regime.generate_trade_setup(symbol)
        if "error" in raw_setup:
            return _meta.wrap(raw_setup, _interp_meta(raw_setup))

        # Uses cached _analyze_technicals — no second network call
        raw_regime = regime.detect_market_regime(symbol)
        ms_data = _build_market_structure(raw_regime)
        if "error" in ms_data:
            return _meta.wrap(ms_data, _interp_meta(ms_data))

        ms = ms_data["market_structure"]
        ii = ms["indicator_interpretation"]

        # Replace old predictive reasoning with observation-only strings
        reasoning = _generate_reasoning(
            price=ms["price"],
            ema20=ms["ema20"],
            ema50=ms["ema50"],
            adx=ms["adx"],
            rsi=ms["rsi"],
            price_above_ema20=ms["price_above_ema20"],
            ema20_above_ema50=ms["ema20_above_ema50"],
            adx_above_25=ms["adx_above_25"],
            rsi_above_60=ms["rsi_above_60"],
            adx_note=ii["adx_note"],
            rsi_note=ii["rsi_note"],
            descriptor=ms["descriptor"],
        )

        # Strip synthetic conviction fields; inject market_structure + new reasoning
        data = {k: v for k, v in raw_setup.items() if k not in _SETUP_FIELDS_TO_DELETE}
        data["reasoning"] = reasoning
        data["market_structure"] = ms
        data["_migration"] = ms_data["_migration"]

        return _meta.wrap(data, _interp_meta(data))

    @mcp.tool()
    def recommend_strategy(symbol: str) -> dict:
        """Recommend an options strategy based on the detected market regime.

        Maps trending, neutral, range-bound, and breakout conditions to
        common options structures such as spreads, condors, and straddles.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
        """
        data = regime.recommend_strategy(symbol)
        return _meta.wrap(data, _interp_meta(data))

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
