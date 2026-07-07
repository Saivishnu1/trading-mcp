from mcp.server.fastmcp import FastMCP

from src import meta as _meta
from src.intelligence.vix import get_india_vix as _get_india_vix
from src.intelligence.global_pulse import get_global_pulse as _get_global_pulse
from src.intelligence.events import get_upcoming_events as _get_upcoming_events


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_india_vix() -> dict:
        """Get the current India VIX (volatility index) level and interpretation.

        Returns the VIX level, 52-week high/low, percentile rank, and a
        plain-English interpretation of market fear/complacency.

        VIX < 12  → Complacency (historically precedes corrections)
        VIX 12-15 → Calm, normal conditions
        VIX 15-20 → Mild uncertainty
        VIX 20-25 → Elevated fear, increase caution
        VIX > 25  → Extreme fear / systemic stress

        No authentication required.
        """
        data = _get_india_vix()
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_INVALID if "error" in data else _meta.DQ_VALID,
            source="yfinance",
            account_type="MARKET_DATA_ONLY",
            stale_threshold_seconds=300,
            limitations=["^INDIAVIX via yfinance; 15-min delayed during session."],
        )
        return _meta.wrap(data, m)

    @mcp.tool()
    def get_global_pulse() -> dict:
        """Get a snapshot of global macro signals relevant to Indian equity markets.

        Returns today's change % for crude oil, gold, the US dollar index,
        S&P 500, and US 10-year yield, together with a plain-English
        description of the India-specific impact of each move.

        Also returns an overall_sentiment: RISK_ON / RISK_OFF / NEUTRAL.

        No authentication required.
        """
        data = _get_global_pulse()
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_INVALID if "error" in data else _meta.DQ_VALID,
            source="yfinance",
            account_type="MARKET_DATA_ONLY",
            stale_threshold_seconds=900,
            limitations=["Global asset prices via yfinance; ~15-min delayed."],
        )
        return _meta.wrap(data, m)

    @mcp.tool()
    def get_upcoming_events(days_ahead: int = 7) -> dict:
        """List known macro events scheduled within the next N days.

        Covers: RBI MPC policy decisions, US FOMC meetings, India CPI/GDP
        releases, and US Non-Farm Payrolls.

        Each event includes the date, event type, description, impact
        (HIGH / MEDIUM / LOW), and days_until.

        Args:
            days_ahead: Horizon in calendar days (default 7, max 30 recommended).

        No authentication required.
        """
        data = _get_upcoming_events(days_ahead)
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_VALID,
            source="internal_calendar",
            account_type="MARKET_DATA_ONLY",
            stale_threshold_seconds=86400,
            limitations=["Event dates are manually maintained; verify against NSE/RBI official calendars."],
        )
        return _meta.wrap(data, m)
