from __future__ import annotations

import base64
from datetime import date, timedelta
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.tools.charts import get_price_chart_impl, get_indicator_chart_impl, get_option_chart_impl


def is_valid_png_base64(b64_str: str) -> bool:
    try:
        decoded = base64.b64decode(b64_str)
        # PNG magic bytes header: 89 50 4E 47 0D 0A 1A 0A
        return decoded.startswith(b"\x89PNG\r\n\x1a\n")
    except Exception:
        return False


@pytest.mark.anyio
async def test_get_price_chart():
    t = date.today()
    mock_candles = [
        {"datetime": (t - timedelta(days=2)).isoformat() + "T09:15:00", "open": 24000.0, "high": 24100.0, "low": 23900.0, "close": 24050.0, "volume": 10000},
        {"datetime": (t - timedelta(days=1)).isoformat() + "T09:15:00", "open": 24050.0, "high": 24200.0, "low": 24000.0, "close": 24150.0, "volume": 15000},
        {"datetime": t.isoformat() + "T09:15:00", "open": 24150.0, "high": 24250.0, "low": 24100.0, "close": 24200.0, "volume": 12000},
    ]
    mock_fetch = AsyncMock(return_value=(mock_candles, "yfinance"))

    with patch("src.tools.charts.fetch_candles", mock_fetch):
        res = await get_price_chart_impl("NIFTY", days=3, show_volume=True, show_ema=True, show_vwap=True, show_bb=True)
        res_data = res["data"]
        assert res_data["symbol"] == "NIFTY"
        assert res_data["interval"] == "day"
        assert is_valid_png_base64(res_data["image"])
        assert res_data["candles"] == 3

        # Test light theme too
        res_light = await get_price_chart_impl("NIFTY", days=3, theme="light")
        assert is_valid_png_base64(res_light["data"]["image"])


@pytest.mark.anyio
async def test_get_indicator_chart():
    t = date.today()
    mock_candles = [
        {"datetime": (t - timedelta(days=2)).isoformat() + "T09:15:00", "open": 24000.0, "high": 24100.0, "low": 23900.0, "close": 24050.0, "volume": 1000},
        {"datetime": (t - timedelta(days=1)).isoformat() + "T09:15:00", "open": 24050.0, "high": 24200.0, "low": 24000.0, "close": 24150.0, "volume": 1000},
        {"datetime": t.isoformat() + "T09:15:00", "open": 24150.0, "high": 24250.0, "low": 24100.0, "close": 24200.0, "volume": 1000},
    ]
    mock_fetch = AsyncMock(return_value=(mock_candles, "yfinance"))

    with patch("src.tools.charts.fetch_candles", mock_fetch):
        res = await get_indicator_chart_impl("NIFTY", days=3)
        res_data = res["data"]
        assert res_data["symbol"] == "NIFTY"
        assert is_valid_png_base64(res_data["image"])


@pytest.mark.anyio
async def test_get_option_chart():
    mock_chain = {
        "records": {
            "underlyingValue": 24270.0,
            "expiryDates": ["2026-07-07"],
            "data": [
                {
                    "strikePrice": 24000.0,
                    "expiryDate": "2026-07-07",
                    "CE": {"openInterest": 1000, "changeinOpenInterest": 10, "lastPrice": 150.0},
                    "PE": {"openInterest": 5000, "changeinOpenInterest": 50, "lastPrice": 10.0},
                },
                {
                    "strikePrice": 24200.0,
                    "expiryDate": "2026-07-07",
                    "CE": {"openInterest": 8000, "changeinOpenInterest": -10, "lastPrice": 50.0},
                    "PE": {"openInterest": 8000, "changeinOpenInterest": 10, "lastPrice": 50.0},
                },
                {
                    "strikePrice": 24500.0,
                    "expiryDate": "2026-07-07",
                    "CE": {"openInterest": 9000, "changeinOpenInterest": 100, "lastPrice": 5.0},
                    "PE": {"openInterest": 100, "changeinOpenInterest": 0, "lastPrice": 200.0},
                }
            ]
        }
    }

    mock_get_chain = MagicMock(return_value=(mock_chain, "2026-07-07", None))

    with patch("src.tools.charts._get_chain_with_cache", mock_get_chain):
        res = await get_option_chart_impl("NIFTY", expiry="2026-07-07")
        res_data = res["data"]
        assert res_data["symbol"] == "NIFTY"
        assert res_data["expiry"] == "2026-07-07"
        assert is_valid_png_base64(res_data["image"])
