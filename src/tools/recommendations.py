from mcp.server.fastmcp import FastMCP

from src.recommendations.engine import (
    recommend_trade as _recommend_trade,
    review_open_trades as _review_open_trades,
    get_daily_brief as _get_daily_brief,
)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def recommend_trade(
        symbol: str,
        capital: float = 100_000,
        risk_percent: float = 1.0,
    ) -> dict:
        """Get a portfolio-aware trade recommendation for a symbol.

        Combines full market analysis (create_trade_plan) with:
          - Existing journal exposure check (warns if you already hold same direction)
          - Event risk intelligence (blocks trade when earnings/catalyst risk ≥ 80)
          - VIX context (blocks when EXTREME; cautions when HIGH)
          - Position size adjustments for HIGH event risk and duplicate exposure

        recommendation:
          ENTER — conditions are favourable, trade is actionable
          WAIT  — conditions are ok but cautions present (size adjusted)
          AVOID — trade not recommended (NEUTRAL signal, extreme risk, or poor RR)

        Also returns: direction, entry/stoploss/target, position_size, strategy,
        event_risk_score, vix_caution, duplicate_exposure, cautions, risk_adjustments.
        """
        return _recommend_trade(symbol=symbol, capital=capital, risk_percent=risk_percent)

    @mcp.tool()
    def review_open_trades() -> dict:
        """Review all currently open journal positions against live market conditions.

        For each open trade (from the journal), fetches live market data and returns:
          action         — HOLD / REDUCE / EXIT (from review_trade)
          thesis_status  — VALID / WEAKENING / INVALIDATED
          current_price  — live price
          current_pnl    — unrealised P&L in absolute terms
          stoploss_breached — true if current price has passed the logged stoploss
          target_reached    — true if current price has reached the logged target

        Summary includes: total_open, hold/reduce/exit counts,
        total_unrealised_pnl, at_risk_count (stoploss breached).

        Does not require an active broker session — uses journal + yfinance.
        """
        return _review_open_trades()

    @mcp.tool()
    def get_daily_brief() -> dict:
        """Get a morning briefing combining market context and open position review.

        market_context:
          vix, vix_caution, overall_risk_score, overall_risk_rating,
          global_sentiment, upcoming_events (next 3 days)

        open_positions: full review_open_trades() result

        alerts: EXIT signals, stoploss breaches, upcoming HIGH-impact events

        summary: plain-English one-paragraph briefing

        Does not require an active broker session.
        """
        return _get_daily_brief()
