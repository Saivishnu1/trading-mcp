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

# Regime labels encoding directional bias — removed from reasoning strings in Phase 22F.
_FORBIDDEN_REGIME_LABELS = {"NEUTRAL_BULLISH", "NEUTRAL_BEARISH"}


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


def _clean_reasoning(reasoning: list) -> list:
    """Remove reasoning strings that reference regime labels deleted in Phase 22F."""
    return [r for r in reasoning if not any(label in r for label in _FORBIDDEN_REGIME_LABELS)]


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


def _clean_generate_setup(raw: dict) -> dict:
    """Strip synthetic conviction fields from generate_trade_setup service output."""
    if "error" in raw:
        return raw
    clean = {k: v for k, v in raw.items() if k not in _SETUP_FIELDS_TO_DELETE}
    if "reasoning" in clean and isinstance(clean["reasoning"], list):
        clean["reasoning"] = _clean_reasoning(clean["reasoning"])
    # TODO Phase 23: remove _migration block from output
    # Keep only meta["schema_version"] going forward
    # _migration is temporary compatibility signal only
    clean["_migration"] = {
        "regime_removed": True,
        "replacement": "market_structure",
        "schema_version": 5,
    }
    return clean


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
        - indicator_interpretation = UNVALIDATED notes only
        - All interpretation fields are UNVALIDATED

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
        """
        raw = regime.generate_trade_setup(symbol)
        data = _clean_generate_setup(raw)
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
