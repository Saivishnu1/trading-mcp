from mcp.server.fastmcp import FastMCP

from src import meta as _meta
from src.catalyst.earnings import get_earnings_calendar as _get_earnings_calendar
from src.catalyst.news import check_move_news_correlation as _check_move_news_correlation
from src.market.symbols import normalize_symbol_extended as _norm


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_earnings_calendar(symbol: str) -> dict:
        """Get the next earnings date, EPS/revenue estimates, and upcoming corporate actions.

        Returns structured data including:
          next_earnings_date       — ISO date string or null
          days_until_earnings      — calendar days until next earnings
          earnings_proximity_risk  — IMMINENT / VERY_HIGH / HIGH / MEDIUM / LOW / N/A
          earnings_proximity_score — 0-100 component score
          eps_estimate             — consensus EPS estimate (or null)
          revenue_estimate         — consensus revenue estimate (or null)
          upcoming_dividends       — dividends with ex-date within 30 days
          upcoming_splits          — stock splits with ex-date within 30 days
          corporate_action_risk    — HIGH / MEDIUM / LOW based on nearest action

        For index symbols (NIFTY, BANKNIFTY) earnings are not applicable —
        a structured response is still returned with null date fields and a note.

        Args:
            symbol: NSE symbol, index alias, or exchange-prefixed form.

        No authentication required.
        """
        sym, corrected, fmt = _norm(symbol, "get_earnings_calendar")
        if not symbol.strip():
            return _meta.make_symbol_error(symbol, "get_earnings_calendar")
        _norm_kw: dict = dict(
            symbol_corrected=corrected,
            symbol_original=symbol if corrected else None,
            symbol_normalized=sym if corrected else None,
            symbol_format_applied=fmt if corrected else None,
        )
        result = _get_earnings_calendar(sym)
        result.setdefault("meta", _meta.build_meta(
            type_=_meta.TYPE_INTERPRETATION,
            validation_status=_meta.VALIDATION_UNVALIDATED,
            data_quality=_meta.DQ_INVALID if "error" in result else _meta.DQ_VALID,
            source="yfinance/news",
            account_type="MARKET_DATA_ONLY",
            **_norm_kw,
        ))
        return result

    @mcp.tool()
    def check_move_news_correlation(symbol: str, threshold_pct: float = 3.0) -> dict:
        """When a position's underlying has moved more than threshold_pct
        intraday, surface the top 1-2 relevant headlines alongside the move
        (Priority B11, 2026-07-11) — avoids a manual web search to explain a
        large move (e.g. Iran ceasefire status, Qatar LNG halt, OPEC+ output
        changes) that only made sense after checking outside sources.

        Move % is last_price vs. previous_close. No news fetch happens
        unless the move actually exceeds threshold_pct.

        Caveat: yfinance's news feed is NSE/global-equity-oriented and has
        thin coverage for MCX commodity futures tickers — this works well
        for NIFTY/SENSEX/equity positions, less so for MCX symbols.

        Args:
            symbol: NSE symbol, index alias, or exchange-prefixed form.
            threshold_pct: minimum |move %| to trigger a news fetch (default 3.0).
        """
        sym, corrected, fmt = _norm(symbol, "check_move_news_correlation")
        if not symbol.strip():
            return _meta.make_symbol_error(symbol, "check_move_news_correlation")
        _norm_kw: dict = dict(
            symbol_corrected=corrected,
            symbol_original=symbol if corrected else None,
            symbol_normalized=sym if corrected else None,
            symbol_format_applied=fmt if corrected else None,
        )
        data = _check_move_news_correlation(sym, threshold_pct)
        m = _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_INVALID if "error" in data else _meta.DQ_VALID,
            source="yfinance",
            account_type="MARKET_DATA_ONLY",
            limitations=["yfinance news coverage is thin for MCX commodity futures tickers."],
            **_norm_kw,
        )
        return _meta.wrap(data, m)
