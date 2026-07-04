from mcp.server.fastmcp import FastMCP
from src import meta as _meta

from src.market.symbols import normalize_symbol_extended as _norm
from src.catalyst.earnings import get_earnings_calendar as _get_earnings_calendar


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
