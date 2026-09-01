from mcp.server.fastmcp import FastMCP

from src.portfolio_intelligence.service import (
    get_portfolio_exposure_breakdown as _get_portfolio_exposure_breakdown,
)
from src.portfolio_intelligence.service import (
    get_portfolio_risk_report as _get_portfolio_risk_report,
)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_portfolio_risk_report() -> dict:
        """Get a comprehensive risk report for your current portfolio.

        Combines per-position analysis (review_trade + market risk score)
        with portfolio-level aggregation:

          portfolio_risk_score  — value-weighted average of per-position scores (0-100)
          rating                — LOW / MODERATE / HIGH / EXTREME
          diversification_score — HHI-based, 0 (1 stock) to ~100 (many equal weights)
          concentration_risk    — largest single position % + flag if > 30%
          top_risks             — top 3 positions by risk score
          recommendations       — EXIT / REDUCE signals + concentration + risk level
          per_position_analysis — symbol, risk_score, regime, review_action, thesis_status

        Requires an active session (call zerodha_login first).
        """
        return _get_portfolio_risk_report()

    @mcp.tool()
    def get_portfolio_exposure_breakdown() -> dict:
        """Get a fast exposure and concentration breakdown of your portfolio.

        Uses raw portfolio data only — no per-symbol analysis calls, so this
        is fast and works without waiting for regime detection.

        Returns:
          long_exposure / short_exposure / net_exposure / total_invested
          largest_position   — top holding by current value + % of portfolio
          top_exposures      — top 5 positions by value
          concentration_metrics — max single position %, HHI diversification score

        Requires an active session (call zerodha_login first).
        """
        return _get_portfolio_exposure_breakdown()
