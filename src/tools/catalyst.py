from mcp.server.fastmcp import FastMCP

from src.catalyst.news import (
    _aggregate_sentiment,
    get_symbol_news as _get_symbol_news,
)
from src.catalyst.earnings import get_earnings_calendar as _get_earnings_calendar
from src.catalyst.event_risk import get_event_risk as _get_event_risk


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_symbol_news(symbol: str, count: int = 10) -> dict:
        """Get recent news headlines for a stock or index symbol.

        Returns up to *count* articles (default 10, max 50) with per-article
        sentiment classification (POSITIVE / NEGATIVE / NEUTRAL) based on
        keyword matching. No ML model or external API key required.

        Each headline includes:
          title        — article headline
          publisher    — news source
          published_at — ISO-8601 UTC timestamp
          link         — article URL
          sentiment    — POSITIVE / NEGATIVE / NEUTRAL

        For index symbols (NIFTY, BANKNIFTY) news reflects broad market coverage.

        Args:
            symbol: NSE symbol, index alias, or exchange-prefixed (e.g. NSE:INFY,
                    INFY, NIFTY, BANKNIFTY).
            count:  Max articles to return (default 10).

        No authentication required.
        """
        return _get_symbol_news(symbol, count)

    @mcp.tool()
    def get_news_sentiment(symbol: str) -> dict:
        """Get aggregate news sentiment for a symbol based on recent headlines.

        Internally calls get_symbol_news (cached) and aggregates per-article
        sentiment into a single score. No additional yfinance fetch is made.

        Returns:
          sentiment            — VERY_POSITIVE / POSITIVE / NEUTRAL /
                                 NEGATIVE / VERY_NEGATIVE
          sentiment_score      — continuous score from -1.0 to +1.0
          positive_count       — articles with positive keyword hits
          negative_count       — articles with negative keyword hits
          neutral_count        — articles with no keyword signal
          total_articles       — total fetched
          summary              — one-line plain-English summary
          top_positive_headline — best positive headline (or null)
          top_negative_headline — most negative headline (or null)

        Args:
            symbol: NSE symbol, index alias, or exchange-prefixed form.

        No authentication required.
        """
        news = _get_symbol_news(symbol)
        sentiment = _aggregate_sentiment(news.get("headlines", []))
        return {
            "symbol": symbol.upper().strip().split(":")[-1],
            **sentiment,
        }

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
        return _get_earnings_calendar(symbol)

    @mcp.tool()
    def get_event_risk(symbol: str) -> dict:
        """Get a composite event risk score (0-100) for a symbol.

        Aggregates three signals:
          Earnings proximity   40% weight  (days until next earnings)
          News sentiment       30% weight  (keyword-based headline scoring)
          Market risk score    30% weight  (Phase 10 composite — VIX/events/PCR/regime)

        Returns:
          event_risk_score         — 0 (no risk) to 100 (extreme risk)
          event_risk_rating        — LOW / MODERATE / HIGH / EXTREME
          confidence               — 1.0 (all data) / 0.8 (2 sources) /
                                     0.5 (market only) / 0.3 (no market)
          components               — per-component scores and weights
          factors                  — list explaining each component
          nearest_catalyst         — soonest catalyst by date within 30 days
          highest_impact_catalyst  — highest-priority catalyst (EARNINGS > SPLIT > DIVIDEND)
          recommendation           — plain-English action guidance

        A high score does NOT mean sell — it means reduce size or use
        defined-risk structures. Use alongside technical analysis.

        Args:
            symbol: NSE symbol, index alias, or exchange-prefixed form.

        No authentication required.
        """
        return _get_event_risk(symbol)
