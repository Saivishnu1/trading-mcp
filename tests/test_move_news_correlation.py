"""Tests for check_move_news_correlation (Priority B11, 2026-07-11) —
src/catalyst/news.py and its MCP tool wrapper in src/tools/catalyst.py.

No news fetch happens unless the move actually exceeds threshold_pct — the
whole point of gating on a threshold. All external calls (get_market,
yfinance news) are mocked.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP as _FastMCP


def _quote(last_price, previous_close):
    return {"last_price": last_price, "previous_close": previous_close}


class TestCheckMoveNewsCorrelation:
    def test_triggers_when_move_exceeds_threshold(self):
        from src.catalyst import news

        mock_market = MagicMock()
        mock_market.get_quote.return_value = _quote(285.0, 316.0)  # -9.8%
        with patch("src.market.get_market", return_value=mock_market), \
             patch.object(news, "get_symbol_news", return_value={
                 "headlines": [{"title": "Qatar LNG halt reported"}, {"title": "OPEC+ raises output"}],
             }):
            result = news.check_move_news_correlation("NATGASMINI", threshold_pct=3.0)

        assert result["triggered"] is True
        assert result["change_pct"] == pytest.approx(-9.81, abs=0.05)
        assert len(result["headlines"]) == 2

    def test_no_headlines_fetched_when_below_threshold(self):
        from src.catalyst import news

        mock_market = MagicMock()
        mock_market.get_quote.return_value = _quote(101.0, 100.0)  # +1%
        with patch("src.market.get_market", return_value=mock_market), \
             patch.object(news, "get_symbol_news") as mock_get_news:
            result = news.check_move_news_correlation("INFY", threshold_pct=3.0)

        assert result["triggered"] is False
        assert result["headlines"] == []
        mock_get_news.assert_not_called()

    def test_headlines_capped_at_two(self):
        from src.catalyst import news

        mock_market = MagicMock()
        mock_market.get_quote.return_value = _quote(90.0, 100.0)  # -10%
        with patch("src.market.get_market", return_value=mock_market), \
             patch.object(news, "get_symbol_news", return_value={
                 "headlines": [{"title": f"Headline {i}"} for i in range(5)],
             }):
            result = news.check_move_news_correlation("NIFTY", threshold_pct=3.0)

        assert len(result["headlines"]) == 2

    def test_negative_move_triggers_via_absolute_value(self):
        from src.catalyst import news

        mock_market = MagicMock()
        mock_market.get_quote.return_value = _quote(90.0, 100.0)  # -10%
        with patch("src.market.get_market", return_value=mock_market), \
             patch.object(news, "get_symbol_news", return_value={"headlines": []}):
            result = news.check_move_news_correlation("NIFTY", threshold_pct=3.0)

        assert result["triggered"] is True
        assert result["change_pct"] == -10.0

    def test_missing_quote_data_returns_error_not_exception(self):
        from src.catalyst import news

        mock_market = MagicMock()
        mock_market.get_quote.return_value = {"last_price": None, "previous_close": None}
        with patch("src.market.get_market", return_value=mock_market):
            result = news.check_move_news_correlation("INFY")

        assert "error" in result

    def test_quote_fetch_exception_returns_error_not_exception(self):
        from src.catalyst import news

        mock_market = MagicMock()
        mock_market.get_quote.side_effect = RuntimeError("network down")
        with patch("src.market.get_market", return_value=mock_market):
            result = news.check_move_news_correlation("INFY")

        assert "error" in result


class TestCheckMoveNewsCorrelationTool:
    def _tools(self):
        from src.tools import catalyst as catalyst_tools
        mcp = _FastMCP("test")
        catalyst_tools.register(mcp)
        return {t.name: t for t in mcp._tool_manager.list_tools()}

    def test_tool_wraps_data_and_meta(self):
        mock_market = MagicMock()
        mock_market.get_quote.return_value = _quote(285.0, 316.0)
        with patch("src.market.get_market", return_value=mock_market), \
             patch("src.catalyst.news.get_symbol_news", return_value={
                 "headlines": [{"title": "Qatar LNG halt reported"}],
             }):
            tools = self._tools()
            result = tools["check_move_news_correlation"].fn(symbol="NATGASMINI", threshold_pct=3.0)

        assert result["data"]["triggered"] is True
        assert "MCX" in result["meta"]["limitations"][0]

    def test_empty_symbol_returns_symbol_error(self):
        tools = self._tools()
        result = tools["check_move_news_correlation"].fn(symbol="   ")
        assert result["status"] == "SYMBOL_ERROR"
