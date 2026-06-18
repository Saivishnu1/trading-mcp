from mcp.server.fastmcp import FastMCP

from src.journal.service import (
    log_trade as _log_trade,
    close_trade as _close_trade,
    get_open_trades as _get_open_trades,
    get_trade_history as _get_trade_history,
    get_performance_analytics as _get_performance_analytics,
)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def log_trade(
        symbol: str,
        direction: str,
        entry_price: float,
        quantity: int | None = None,
        strategy: str | None = None,
        rationale: str | None = None,
        stoploss: float | None = None,
        target: float | None = None,
        risk_reward: float | None = None,
        regime: str | None = None,
        signal: str | None = None,
        risk_score: int | None = None,
        analysis_snapshot: dict | None = None,
        trade_type: str = "EQUITY",
        created_by: str = "MANUAL",
        tags: list[str] | None = None,
        notes: str | None = None,
    ) -> dict:
        """Log a new trade to your personal journal.

        Required: symbol (e.g. 'INFY'), direction ('LONG' or 'SHORT'), entry_price.

        Optional context fields (populate from prior analysis calls in the session):
          regime, signal, risk_score   — from detect_market_regime / get_market_risk_score
          analysis_snapshot            — JSON dict of any additional analysis context
          stoploss / target            — risk_reward is auto-calculated if both provided
          trade_type                   — 'EQUITY' (default) | 'OPTIONS' | 'FUTURES' | 'INDEX'
          created_by                   — 'MANUAL' (default) | 'CLAUDE' | 'AUTOMATED'
          tags                         — list of labels, e.g. ['momentum', 'event-play']

        Returns the full trade record with a trade_id (format: TRD-xxxxxxxx).
        Use trade_id with close_trade() to finalise the position.
        """
        return _log_trade(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            quantity=quantity,
            strategy=strategy,
            rationale=rationale,
            stoploss=stoploss,
            target=target,
            risk_reward=risk_reward,
            regime=regime,
            signal=signal,
            risk_score=risk_score,
            analysis_snapshot=analysis_snapshot,
            trade_type=trade_type,
            created_by=created_by,
            tags=tags,
            notes=notes,
        )

    @mcp.tool()
    def close_trade(
        trade_id: str,
        exit_price: float,
        exit_reason: str = "MANUAL",
        notes: str | None = None,
    ) -> dict:
        """Close an open trade and calculate final P&L.

        trade_id: the TRD-xxxxxxxx identifier returned by log_trade.
        exit_reason: TARGET_HIT | STOPLOSS_HIT | MANUAL | THESIS_INVALIDATED | EXPIRED | CANCELLED
        notes: optional closing note appended to any existing notes.

        Returns the closed trade record including pnl, pnl_percent, and holding_days.
        """
        return _close_trade(
            trade_id=trade_id,
            exit_price=exit_price,
            exit_reason=exit_reason,
            notes=notes,
        )

    @mcp.tool()
    def get_open_trades(symbol: str | None = None) -> dict:
        """List all currently open trades.

        symbol: optional filter (e.g. 'INFY'). Returns all open positions if omitted.

        Response: { count, trades: [ full trade records ] }
        """
        return _get_open_trades(symbol=symbol)

    @mcp.tool()
    def get_trade_history(
        symbol: str | None = None,
        days: int = 30,
        status: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Query trade history with optional filters and a performance summary.

        symbol:  filter by symbol (e.g. 'INFY')
        days:    look-back window in calendar days (default 30)
        status:  'OPEN' | 'CLOSED' — omit to see all
        limit:   max records to return (default 50)

        Response includes:
          count, filters, trades (full records)
          summary: total_trades, win_count, loss_count, win_rate_pct,
                   total_pnl, avg_pnl, avg_holding_days, best_trade, worst_trade
        """
        return _get_trade_history(
            symbol=symbol,
            days=days,
            status=status,
            limit=limit,
        )

    @mcp.tool()
    def get_performance_analytics(
        symbol: str | None = None,
        days: int = 365,
        min_sample: int = 10,
    ) -> dict:
        """Measure realized trading edge from your CLOSED journal trades.

        Answers "does the model actually work?" by bucketing closed trades by
        signal, regime, and entry-confidence band, and reporting win rate,
        average P&L, total P&L, and an overall profit factor per bucket.

        symbol:     optional filter (e.g. 'INFY'); omit for the whole book
        days:       look-back window in calendar days (default 365)
        min_sample: buckets with fewer trades are flagged low_sample (default 10)

        Response:
          closed_trades, overall (incl. profit_factor),
          by_signal / by_regime / by_confidence_band — each:
            { trades, wins, win_rate_pct, avg_pnl, total_pnl, low_sample }
          notes — plain-English edge / confidence-calibration / sample warnings

        Note: confidence buckets require analysis_snapshot.confidence to have
        been stored at log_trade time; otherwise trades fall in the 'unknown' band.
        """
        return _get_performance_analytics(
            symbol=symbol,
            days=days,
            min_sample=min_sample,
        )
