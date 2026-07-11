"""Tests for src/mcx/benchmark.py and src/mcx/benchmark_sources.py (Priority A4).

check_benchmark_divergence only covers CRUDEOIL/CRUDEOILM/NATURALGAS/NATGASMINI
via OilPriceAPI (WTI/Henry Hub) — see docs/research/mcx_scope_20260711.md for why
MCX-side price data is caller-supplied rather than fetched (no working MCX price
source exists in this platform). All external calls are mocked — no real network.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP as _FastMCP

from src import meta as _meta
from src.mcx import benchmark as benchmark_mod


def _mock_client(latest_price=None, prior_price=None, status="success"):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)

    def _get(path, params=None, headers=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if path == "/prices/latest":
            resp.json.return_value = (
                {"status": status, "data": {"price": latest_price}}
                if latest_price is not None else {"status": "error"}
            )
        elif path == "/prices/past_day":
            resp.json.return_value = (
                {"status": status, "data": [{"price": prior_price}]}
                if prior_price is not None else {"status": "error"}
            )
        return resp

    client.get = MagicMock(side_effect=_get)
    return client


class TestBenchmarkSources:
    def test_fetch_latest_price_returns_float(self):
        from src.mcx.benchmark_sources import fetch_latest_price
        with patch("src.mcx.benchmark_sources._get_client", return_value=_mock_client(latest_price=72.5)):
            assert fetch_latest_price("WTI_USD") == 72.5

    def test_fetch_latest_price_none_on_error_status(self):
        from src.mcx.benchmark_sources import fetch_latest_price
        with patch("src.mcx.benchmark_sources._get_client", return_value=_mock_client(latest_price=None)):
            assert fetch_latest_price("WTI_USD") is None

    def test_fetch_latest_price_none_on_exception(self):
        from src.mcx.benchmark_sources import fetch_latest_price
        broken_client = MagicMock()
        broken_client.__enter__ = MagicMock(side_effect=RuntimeError("network down"))
        with patch("src.mcx.benchmark_sources._get_client", return_value=broken_client):
            assert fetch_latest_price("WTI_USD") is None

    def test_fetch_benchmark_change_pct_computes_correctly(self):
        from src.mcx.benchmark_sources import fetch_benchmark_change_pct
        with patch("src.mcx.benchmark_sources._get_client", return_value=_mock_client(latest_price=110.0, prior_price=100.0)):
            assert fetch_benchmark_change_pct("NATURAL_GAS_USD") == 10.0

    def test_fetch_benchmark_change_pct_none_when_prior_missing(self):
        from src.mcx.benchmark_sources import fetch_benchmark_change_pct
        with patch("src.mcx.benchmark_sources._get_client", return_value=_mock_client(latest_price=110.0, prior_price=None)):
            assert fetch_benchmark_change_pct("WTI_USD") is None


class TestCheckBenchmarkDivergence:
    def setup_method(self):
        benchmark_mod._CACHE.clear()

    def test_unsupported_symbol_returns_error(self):
        result = benchmark_mod.check_benchmark_divergence("GOLD", mcx_change_pct=1.0)
        assert result["error"] == "unsupported_symbol"

    def test_flags_when_divergence_exceeds_threshold(self):
        with patch("src.mcx.benchmark.fetch_benchmark_change_pct", return_value=0.2):
            result = benchmark_mod.check_benchmark_divergence("NATGASMINI", mcx_change_pct=-9.8, threshold_pct=3.0)
        assert result["flag"] is not None
        assert "NATGASMINI" in result["flag"]
        assert result["divergence_pct"] == pytest.approx(10.0, abs=0.01)

    def test_no_flag_when_within_threshold(self):
        with patch("src.mcx.benchmark.fetch_benchmark_change_pct", return_value=1.5):
            result = benchmark_mod.check_benchmark_divergence("CRUDEOIL", mcx_change_pct=2.0, threshold_pct=3.0)
        assert result["flag"] is None
        assert result["divergence_pct"] == pytest.approx(0.5, abs=0.01)

    def test_crudeoilm_maps_to_same_benchmark_as_crudeoil(self):
        with patch("src.mcx.benchmark.fetch_benchmark_change_pct", return_value=1.0) as mock_fetch:
            benchmark_mod.check_benchmark_divergence("CRUDEOILM", mcx_change_pct=1.0)
        mock_fetch.assert_called_once_with("WTI_USD")

    def test_benchmark_unavailable_returns_error_not_exception(self):
        with patch("src.mcx.benchmark.fetch_benchmark_change_pct", return_value=None):
            result = benchmark_mod.check_benchmark_divergence("NATURALGAS", mcx_change_pct=5.0)
        assert result["error"] == "benchmark_source_unavailable"

    def test_second_call_within_ttl_is_cache_hit(self):
        with patch("src.mcx.benchmark.fetch_benchmark_change_pct", return_value=1.0) as mock_fetch:
            first = benchmark_mod.check_benchmark_divergence("CRUDEOIL", mcx_change_pct=1.0)
            second = benchmark_mod.check_benchmark_divergence("CRUDEOIL", mcx_change_pct=1.0)
        assert first["from_cache"] is False
        assert second["from_cache"] is True
        mock_fetch.assert_called_once()


class TestCheckBenchmarkDivergenceTool:
    def setup_method(self):
        benchmark_mod._CACHE.clear()

    def _tools(self):
        from src.tools import mcx as mcx_tools
        mcp = _FastMCP("test")
        mcx_tools.register(mcp)
        return {t.name: t for t in mcp._tool_manager.list_tools()}

    def test_tool_wraps_data_and_meta(self):
        tools = self._tools()
        with patch("src.mcx.benchmark.fetch_benchmark_change_pct", return_value=0.2):
            result = tools["check_benchmark_divergence"].fn(symbol="NATGASMINI", mcx_change_pct=-9.8)
        assert result["data"]["flag"] is not None
        assert result["meta"]["source"] == "oilpriceapi"

    def test_tool_reflects_error_in_data_quality(self):
        tools = self._tools()
        result = tools["check_benchmark_divergence"].fn(symbol="GOLD", mcx_change_pct=1.0)
        assert "error" in result["data"]
        assert result["meta"]["data_quality"] == _meta.DQ_INVALID
