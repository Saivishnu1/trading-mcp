from mcp.server.fastmcp import FastMCP

from src.analysis import regime
from src import meta as _meta

_INTERP_LIMITATIONS = [
    "Regime classification has not been backtested for edge.",
    "Phase 20A: regime-classifier edge not demonstrated on out-of-sample data.",
    "Phase 21: momentum signals produced negative spreads in cross-sectional screen.",
]

# Fields deprecated in Phase 22 — present in responses but scheduled for removal.
# Removal happens in Commit 6 (two weeks after Commit 5).
_DEPRECATED_FIELDS = ["confidence", "signal"]
_DEPRECATION_NOTE = (
    "Fields 'confidence' and 'signal' have no demonstrated predictive validity. "
    "Phase 20A: regime-classifier edge not demonstrated. "
    "Phase 21: momentum signals produced negative spreads. "
    "These fields are present for backward compatibility and will be removed "
    "in Phase 22 Commit 6. Do not use them for trading decisions."
)


def _interp_meta(data: dict, *, flag_deprecated: bool = False) -> dict:
    dq = _meta.DQ_INVALID if "error" in data else _meta.DQ_VALID
    dep_fields = _DEPRECATED_FIELDS if flag_deprecated else []
    dep_note = _DEPRECATION_NOTE if flag_deprecated else None
    return _meta.build_meta(
        type_=_meta.TYPE_INTERPRETATION,
        validation_status=_meta.VALIDATION_UNVALIDATED,
        research_status=_meta.RS_EXPERIMENTAL,
        data_quality=dq,
        source="yfinance",
        account_type="MARKET_DATA_ONLY",
        limitations=_INTERP_LIMITATIONS,
        deprecated_fields_present=dep_fields,
        deprecation_note=dep_note,
    )


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
        """Detect the current market regime for a symbol.

        Reuses the same daily technical snapshot logic as the technical tools
        and classifies the symbol into a deterministic market regime.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
        """
        data = regime.detect_market_regime(symbol)
        return _meta.wrap(data, _interp_meta(data, flag_deprecated=True))

    @mcp.tool()
    def generate_trade_setup(symbol: str) -> dict:
        """Generate a deterministic trade setup for a symbol.

        Uses the bundled technical analysis plus detected market regime to
        output BUY, SELL, NEUTRAL, NEUTRAL_BULLISH, or NEUTRAL_BEARISH
        with deterministic entry zones, targets, and reasoning.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', 'NSE:INFY', or a raw yfinance ticker.
        """
        data = regime.generate_trade_setup(symbol)
        return _meta.wrap(data, _interp_meta(data, flag_deprecated=True))

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
