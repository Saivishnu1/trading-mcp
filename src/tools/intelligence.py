from mcp.server.fastmcp import FastMCP

from src.intelligence.vix import get_india_vix as _get_india_vix
from src.intelligence.global_pulse import get_global_pulse as _get_global_pulse
from src.intelligence.events import get_upcoming_events as _get_upcoming_events
from src.intelligence.risk import get_market_risk_score as _get_market_risk_score


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
        return _get_india_vix()

    @mcp.tool()
    def get_global_pulse() -> dict:
        """Get a snapshot of global macro signals relevant to Indian equity markets.

        Returns today's change % for crude oil, gold, the US dollar index,
        S&P 500, and US 10-year yield, together with a plain-English
        description of the India-specific impact of each move.

        Also returns an overall_sentiment: RISK_ON / RISK_OFF / NEUTRAL.

        No authentication required.
        """
        return _get_global_pulse()

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
        return _get_upcoming_events(days_ahead)

    @mcp.tool()
    def get_market_risk_score(symbol: str = "NIFTY") -> dict:
        """Get a composite market risk score (0-100) for a symbol.

        Aggregates four signals:
          VIX caution level     35% weight
          Upcoming event proximity  30% weight
          PCR interpretation    20% weight
          Market regime         15% weight

        Returns:
          score:          0 (no risk) to 100 (extreme risk)
          rating:         LOW / MODERATE / HIGH / EXTREME
          factors:        list explaining each component's contribution
          recommendation: one-sentence action guidance
          inputs:         raw component scores for transparency

        A high score does NOT mean sell — it means reduce size or use
        defined-risk structures. Use alongside technical analysis.

        Args:
            symbol: 'NIFTY', 'BANKNIFTY', or any analysable symbol (default 'NIFTY').

        No authentication required.
        """
        return _get_market_risk_score(symbol)
