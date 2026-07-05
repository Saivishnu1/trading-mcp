from __future__ import annotations

from datetime import date, timedelta
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.tools.charts import get_price_chart_impl, get_indicator_chart_impl, get_option_chart_impl
from src.charts.utils import validate_png


def _make_mock_candles(count: int) -> list[dict]:
    t = date.today()
    candles = []
    for i in range(count):
        candles.append({
            "datetime": (t - timedelta(days=count - i)).isoformat() + "T09:15:00",
            "open": 24000.0 + i * 10,
            "high": 24080.0 + i * 10,
            "low": 23980.0 + i * 10,
            "close": 24050.0 + i * 10,
            "volume": 10000 + i * 100,
        })
    return candles


@pytest.mark.anyio
async def test_get_price_chart():
    mock_candles = _make_mock_candles(20)
    mock_fetch = AsyncMock(return_value=(mock_candles, "yfinance"))

    with patch("src.tools.charts.fetch_candles", mock_fetch):
        res = await get_price_chart_impl("NIFTY", days=10, show_volume=True, show_ema=True, show_vwap=True, show_bb=True)
        res_data = res["data"]
        assert res_data["symbol"] == "NIFTY"
        assert res_data["interval"] == "day"
        assert validate_png(res_data["image"])
        assert res_data["candles"] == 10
        assert res_data["width"] == 2100
        assert res_data["height"] == 1200
        assert res_data["theme"] == "dark"

        # Test light theme too
        res_light = await get_price_chart_impl("NIFTY", days=10, theme="light")
        assert validate_png(res_light["data"]["image"])
        assert res_light["data"]["theme"] == "light"


@pytest.mark.anyio
async def test_get_indicator_chart():
    mock_candles = _make_mock_candles(20)
    mock_fetch = AsyncMock(return_value=(mock_candles, "yfinance"))

    with patch("src.tools.charts.fetch_candles", mock_fetch):
        res = await get_indicator_chart_impl("NIFTY", days=10)
        res_data = res["data"]
        assert res_data["symbol"] == "NIFTY"
        assert validate_png(res_data["image"])
        assert res_data["width"] == 2100
        assert res_data["height"] == 1500
        assert res_data["theme"] == "dark"


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
        assert validate_png(res_data["image"])
        assert res_data["width"] == 2100
        assert res_data["height"] == 900
        assert res_data["theme"] == "dark"
