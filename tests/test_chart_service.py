"""Candlestick chart data service tests (2026-07-12).

Covers src/execution/chart_service.py: interval mapping, date-range bounding
(reusing chart_awareness's _INDMONEY_MAX_DAYS), the 60s in-memory cache,
and every distinguishable error case. No network calls — INDmoneyBroker
is mocked at the adapter-factory boundary.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from src.execution import chart_service


@pytest.fixture(autouse=True)
def _clear_chart_cache():
    chart_service.clear_cache()
    yield
    chart_service.clear_cache()


def _fake_broker(historical_return=None, token="test-token"):
    broker = AsyncMock()
    broker._token = token
    broker.get_historical_data = AsyncMock(return_value=historical_return or [])
    return broker


@pytest.mark.anyio
async def test_missing_exchange_or_security_id_is_invalid():
    result = await chart_service.get_candles("", "51381", "1D")
    assert result["status"] == "error"
    assert result["error"] == "invalid_security_id"

    result2 = await chart_service.get_candles("NSE", "", "1D")
    assert result2["status"] == "error"
    assert result2["error"] == "invalid_security_id"


@pytest.mark.anyio
async def test_unsupported_interval_rejected():
    result = await chart_service.get_candles("NSE", "51381", "4h")
    assert result["status"] == "error"
    assert result["error"] == "unsupported_interval"


@pytest.mark.anyio
async def test_not_authenticated_when_no_token():
    broker = _fake_broker(token="")
    with patch.object(chart_service, "get_broker_adapter", return_value=broker):
        result = await chart_service.get_candles("NSE", "51381", "1D")
    assert result["status"] == "error"
    assert result["error"] == "not_authenticated"
    broker.get_historical_data.assert_not_awaited()


@pytest.mark.anyio
async def test_no_data_when_broker_returns_empty():
    broker = _fake_broker(historical_return=[])
    with patch.object(chart_service, "get_broker_adapter", return_value=broker):
        result = await chart_service.get_candles("NSE", "51381", "1D")
    assert result["status"] == "error"
    assert result["error"] == "no_data"


@pytest.mark.anyio
async def test_success_normalizes_to_lightweight_charts_shape():
    raw = [
        {"timestamp": 1752000000000, "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 5000},
    ]
    broker = _fake_broker(historical_return=raw)
    with patch.object(chart_service, "get_broker_adapter", return_value=broker):
        result = await chart_service.get_candles("NSE", "51381", "1D")
    assert result["status"] == "ok"
    assert result["cached"] is False
    candle = result["candles"][0]
    assert candle == {"time": 1752000000, "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 5000}


@pytest.mark.parametrize("ui_interval,expected_ind_interval,expected_max_days", [
    ("1m", "1minute", 7),
    ("5m", "5minute", 7),
    ("15m", "15minute", 7),
    ("30m", "30minute", 14),
    ("1h", "60minute", 14),
    ("1D", "1day", 365),
])
@pytest.mark.anyio
async def test_interval_mapping_and_date_range(ui_interval, expected_ind_interval, expected_max_days):
    broker = _fake_broker(historical_return=[
        {"timestamp": 1752000000000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0},
    ])
    with patch.object(chart_service, "get_broker_adapter", return_value=broker):
        await chart_service.get_candles("NSE", "51381", ui_interval)

    broker.get_historical_data.assert_awaited_once()
    call_args = broker.get_historical_data.call_args.args
    assert call_args[0] == "NSE_51381"
    assert call_args[1] == expected_ind_interval
    from datetime import date
    from_date = date.fromisoformat(call_args[2])
    to_date = date.fromisoformat(call_args[3])
    assert (to_date - from_date).days == expected_max_days


@pytest.mark.anyio
async def test_cache_hit_skips_second_broker_call():
    broker = _fake_broker(historical_return=[
        {"timestamp": 1752000000000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0},
    ])
    with patch.object(chart_service, "get_broker_adapter", return_value=broker):
        first = await chart_service.get_candles("NSE", "51381", "1D")
        second = await chart_service.get_candles("NSE", "51381", "1D")
    assert first["cached"] is False
    assert second["cached"] is True
    broker.get_historical_data.assert_awaited_once()  # not called again for the cache hit


@pytest.mark.anyio
async def test_cache_expires_after_ttl():
    broker = _fake_broker(historical_return=[
        {"timestamp": 1752000000000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0},
    ])
    with patch.object(chart_service, "get_broker_adapter", return_value=broker):
        await chart_service.get_candles("NSE", "51381", "1D")
        # Force the cached entry to look 61s old rather than mocking the
        # global time.time() (which every other test in this process also
        # calls) — same pattern already used elsewhere in this codebase for
        # TTL-cache tests.
        key = ("NSE", "51381", "1D")
        ts, candles = chart_service._cache[key]
        chart_service._cache[key] = (ts - 61, candles)
        await chart_service.get_candles("NSE", "51381", "1D")
    assert broker.get_historical_data.await_count == 2  # second call past the 60s TTL refetched


@pytest.mark.anyio
async def test_cache_keyed_by_exchange_security_id_interval():
    # Different security_id must not hit the other contract's cache entry.
    broker = _fake_broker(historical_return=[
        {"timestamp": 1752000000000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0},
    ])
    with patch.object(chart_service, "get_broker_adapter", return_value=broker):
        await chart_service.get_candles("NSE", "51381", "1D")
        result = await chart_service.get_candles("NSE", "99999", "1D")
    assert result["cached"] is False
    assert broker.get_historical_data.await_count == 2
