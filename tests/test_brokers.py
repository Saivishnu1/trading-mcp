"""
Phase 1 — Broker Intelligence tests.

Covers: INDmoneyBroker, ZerodhaBroker, factory, and unified tool helpers.
No real network calls — all HTTP and broker interactions are mocked.
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_httpx_response(status_code: int, json_data=None, text_data: str = ""):
    """Build a minimal mock that behaves like httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text_data
    return resp


def _async_cm(return_value):
    """Return an async context manager whose __aenter__ resolves to return_value."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=return_value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# TestINDmoneyBroker
# ---------------------------------------------------------------------------

class TestINDmoneyBroker:

    def _broker(self, token: str = "test-token"):
        from src.brokers.indmoney import INDmoneyBroker
        with patch.dict(os.environ, {"INDSTOCKS_TOKEN": token}):
            b = INDmoneyBroker()
        b._token = token
        return b

    # --- is_authenticated ---

    @pytest.mark.anyio
    async def test_is_authenticated_no_token(self):
        from src.brokers.indmoney import INDmoneyBroker
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INDSTOCKS_TOKEN", None)
            b = INDmoneyBroker()
        assert await b.is_authenticated() is False

    @pytest.mark.anyio
    async def test_is_authenticated_200(self):
        b = self._broker()
        resp = _make_httpx_response(200, {"user_id": "u1"})
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            result = await b.is_authenticated()
        assert result is True

    @pytest.mark.anyio
    async def test_is_authenticated_403(self):
        b = self._broker()
        resp = _make_httpx_response(403)
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            result = await b.is_authenticated()
        assert result is False

    @pytest.mark.anyio
    async def test_is_authenticated_network_error(self):
        b = self._broker()
        client_mock = MagicMock()
        client_mock.get = AsyncMock(side_effect=Exception("timeout"))
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            result = await b.is_authenticated()
        assert result is False

    # --- get_holdings ---

    @pytest.mark.anyio
    async def test_get_holdings_success(self):
        b = self._broker()
        payload = [
            {
                "trading_symbol": "INFY",
                "exchange_segment": "NSE",
                "quantity": 10,
                "average_price": 1500.0,
                "last_traded_price": 1600.0,
                "pnl_absolute": 1000.0,
                "pnl_percent": 6.67,
            }
        ]
        resp = _make_httpx_response(200, payload)
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            holdings = await b.get_holdings()
        assert len(holdings) == 1
        h = holdings[0]
        assert h.symbol == "INFY"
        assert h.exchange == "NSE"
        assert h.quantity == 10
        assert h.avg_price == 1500.0
        assert h.current_price == 1600.0
        assert h.pnl == 1000.0
        assert h.broker == "indmoney"

    @pytest.mark.anyio
    async def test_get_holdings_empty_token(self):
        from src.brokers.indmoney import INDmoneyBroker
        b = INDmoneyBroker()
        b._token = ""
        result = await b.get_holdings()
        assert result == []

    @pytest.mark.anyio
    async def test_get_holdings_api_500(self):
        b = self._broker()
        resp = _make_httpx_response(500)
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            result = await b.get_holdings()
        assert result == []

    @pytest.mark.anyio
    async def test_get_holdings_network_error(self):
        b = self._broker()
        client_mock = MagicMock()
        client_mock.get = AsyncMock(side_effect=Exception("network error"))
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            result = await b.get_holdings()
        assert result == []

    # --- get_funds ---

    @pytest.mark.anyio
    async def test_get_funds_success(self):
        b = self._broker()
        payload = {
            "status": "success",
            "data": {
                "sod_balance": 4996.47,
                "detailed_avl_balance": {
                    "option_buy": 4449.65,
                    "eq_cnc": 2980.40,
                },
                "realized_pnl": -751.92,
            },
        }
        resp = _make_httpx_response(200, payload)
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            funds = await b.get_funds()
        assert len(funds) == 1
        f = funds[0]
        assert f.available == 4449.65
        assert f.total == 4996.47
        assert f.broker == "indmoney"

    @pytest.mark.anyio
    async def test_get_funds_no_token(self):
        from src.brokers.indmoney import INDmoneyBroker
        b = INDmoneyBroker()
        b._token = ""
        result = await b.get_funds()
        assert result == []

    # --- get_positions ---

    @pytest.mark.anyio
    async def test_get_positions_success(self):
        b = self._broker()
        payload = {
            "status": "success",
            "data": {
                "net_positions": [
                    {
                        "trading_symbol": "NIFTY25MAYFUT",
                        "exchange_segment": "NSE_FNO",
                        "net_quantity": 50,
                        "average_price": 120.0,
                        "last_traded_price": 150.0,
                        "pnl_absolute": 1500.0,
                        "position_type": "open",
                    }
                ],
                "day_positions": [],
            },
        }
        resp = _make_httpx_response(200, payload)
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            positions = await b.get_positions()
        assert len(positions) == 1
        p = positions[0]
        assert p.symbol == "NIFTY25MAYFUT"
        assert p.exchange == "NSE"
        assert p.quantity == 50
        assert p.broker == "indmoney"

    # --- get_orders ---

    @pytest.mark.anyio
    async def test_get_orders_success(self):
        b = self._broker()
        payload = {
            "status": "success",
            "data": [
                {
                    "id": "DRV-28131451",
                    "name": "NIFTY 3 JUL 25700 CE",
                    "security_id": "56998",
                    "txn_type": "BUY",
                    "exchange": "NSE",
                    "segment": "DERIVATIVE",
                    "product": "MARGIN",
                    "traded_qty": 75,
                    "requested_qty": 75,
                    "traded_price": "43.55",
                    "requested_price": "43.55",
                    "status": "SUCCESS",
                }
            ],
        }
        resp = _make_httpx_response(200, payload)
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            orders = await b.get_orders()
        assert len(orders) == 1
        o = orders[0]
        assert o.order_id == "DRV-28131451"
        assert o.symbol == "NIFTY 3 JUL 25700 CE"
        assert o.transaction_type == "BUY"
        assert o.quantity == 75
        assert o.price == 43.55
        assert o.status == "SUCCESS"
        assert o.broker == "indmoney"

    # --- get_option_chain (not_available stub) ---

    @pytest.mark.anyio
    async def test_get_option_chain_not_available(self):
        b = self._broker()
        result = await b.get_option_chain("NIFTY", "2024-06-27")
        assert result["status"] == "not_available"
        assert "coming soon" in result["message"].lower()

    # --- get_greeks (not_available stub) ---

    @pytest.mark.anyio
    async def test_get_greeks_not_available(self):
        b = self._broker()
        result = await b.get_greeks(["BANKNIFTY28MAR24C45100"])
        assert result["status"] == "not_available"
        assert "coming soon" in result["message"].lower()

    # --- to_dict serialization ---

    @pytest.mark.anyio
    async def test_holding_to_dict(self):
        from src.brokers.models import Holding
        h = Holding(
            symbol="INFY", exchange="NSE", quantity=10,
            avg_price=1500.0, current_price=1600.0,
            pnl=1000.0, pnl_percent=6.67, broker="indmoney",
        )
        d = h.to_dict()
        assert d["symbol"] == "INFY"
        assert d["broker"] == "indmoney"
        assert d["quantity"] == 10

    # --- get_historical_data ---

    @pytest.mark.anyio
    async def test_get_historical_data_success(self):
        b = self._broker()
        payload = [[1700000000000, 100.0, 105.0, 99.0, 103.0, 50000]]
        resp = _make_httpx_response(200, payload)
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            candles = await b.get_historical_data("NSE_2885", "1day", "2024-01-01", "2024-01-31")
        assert len(candles) == 1
        assert candles[0]["open"] == 100.0
        assert candles[0]["close"] == 103.0
        assert candles[0]["volume"] == 50000

    @pytest.mark.anyio
    async def test_get_historical_data_no_token(self):
        from src.brokers.indmoney import INDmoneyBroker
        b = INDmoneyBroker()
        b._token = ""
        result = await b.get_historical_data("NSE_2885", "1day", "2024-01-01", "2024-01-31")
        assert result == []


# ---------------------------------------------------------------------------
# TestZerodhaBroker
# ---------------------------------------------------------------------------

class TestZerodhaBroker:

    def _make_fake_broker(self, authenticated=True):
        fake = MagicMock()
        fake.is_authenticated.return_value = authenticated
        return fake

    @pytest.mark.anyio
    async def test_is_authenticated_delegates(self):
        from src.brokers.zerodha import ZerodhaBroker
        b = ZerodhaBroker()
        fake = self._make_fake_broker(True)
        with patch.object(b, "_get_broker", return_value=fake):
            result = await b.is_authenticated()
        assert result is True
        fake.is_authenticated.assert_called_once()

    @pytest.mark.anyio
    async def test_is_authenticated_false_when_broker_raises(self):
        from src.brokers.zerodha import ZerodhaBroker
        b = ZerodhaBroker()
        fake = MagicMock()
        fake.is_authenticated.side_effect = RuntimeError("not logged in")
        with patch.object(b, "_get_broker", return_value=fake):
            result = await b.is_authenticated()
        assert result is False

    @pytest.mark.anyio
    async def test_get_holdings_delegates_and_normalizes(self):
        from src.brokers.zerodha import ZerodhaBroker
        b = ZerodhaBroker()
        raw = [
            {
                "tradingsymbol": "RELIANCE",
                "exchange": "NSE",
                "quantity": 5,
                "average_price": 2500.0,
                "last_price": 2600.0,
                "pnl": 500.0,
            }
        ]
        fake = self._make_fake_broker(True)
        fake.holdings.return_value = raw
        with patch.object(b, "_get_broker", return_value=fake):
            holdings = await b.get_holdings()
        assert len(holdings) == 1
        h = holdings[0]
        assert h.symbol == "RELIANCE"
        assert h.exchange == "NSE"
        assert h.quantity == 5
        assert h.avg_price == 2500.0
        assert h.current_price == 2600.0
        assert h.pnl == 500.0
        assert h.broker == "zerodha"

    @pytest.mark.anyio
    async def test_get_holdings_returns_empty_on_error(self):
        from src.brokers.zerodha import ZerodhaBroker
        b = ZerodhaBroker()
        fake = MagicMock()
        fake.holdings.side_effect = RuntimeError("not authenticated")
        with patch.object(b, "_get_broker", return_value=fake):
            result = await b.get_holdings()
        assert result == []

    @pytest.mark.anyio
    async def test_get_positions_delegates(self):
        from src.brokers.zerodha import ZerodhaBroker
        b = ZerodhaBroker()
        raw = {
            "net": [
                {
                    "tradingsymbol": "INFY",
                    "exchange": "NSE",
                    "quantity": 10,
                    "average_price": 1400.0,
                    "last_price": 1450.0,
                    "pnl": 500.0,
                    "product": "CNC",
                }
            ],
            "day": [],
        }
        fake = self._make_fake_broker(True)
        fake.positions.return_value = raw
        with patch.object(b, "_get_broker", return_value=fake):
            positions = await b.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "INFY"
        assert positions[0].broker == "zerodha"

    @pytest.mark.anyio
    async def test_get_funds_delegates(self):
        from src.brokers.zerodha import ZerodhaBroker
        b = ZerodhaBroker()
        raw = {
            "available": {"live_balance": 75000.0},
            "utilised": {"debits": 25000.0},
        }
        fake = self._make_fake_broker(True)
        fake.margins.return_value = raw
        with patch.object(b, "_get_broker", return_value=fake):
            funds = await b.get_funds()
        assert len(funds) == 1
        f = funds[0]
        assert f.available == 75000.0
        assert f.used == 25000.0
        assert f.total == 100000.0
        assert f.broker == "zerodha"

    @pytest.mark.anyio
    async def test_get_orders_delegates(self):
        from src.brokers.zerodha import ZerodhaBroker
        b = ZerodhaBroker()
        raw = [
            {
                "order_id": "220101000001",
                "tradingsymbol": "TCS",
                "exchange": "NSE",
                "transaction_type": "BUY",
                "quantity": 2,
                "price": 3200.0,
                "status": "COMPLETE",
            }
        ]
        fake = self._make_fake_broker(True)
        fake.orders.return_value = raw
        with patch.object(b, "_get_broker", return_value=fake):
            orders = await b.get_orders()
        assert len(orders) == 1
        o = orders[0]
        assert o.order_id == "220101000001"
        assert o.symbol == "TCS"
        assert o.broker == "zerodha"

    @pytest.mark.anyio
    async def test_get_profile_delegates(self):
        from src.brokers.zerodha import ZerodhaBroker
        b = ZerodhaBroker()
        profile_data = {"user_id": "AB1234", "user_name": "Test User"}
        fake = self._make_fake_broker(True)
        fake.profile.return_value = profile_data
        with patch.object(b, "_get_broker", return_value=fake):
            result = await b.get_profile()
        assert result["user_id"] == "AB1234"

    @pytest.mark.anyio
    async def test_broker_name(self):
        from src.brokers.zerodha import ZerodhaBroker
        b = ZerodhaBroker()
        assert b.broker_name == "zerodha"


# ---------------------------------------------------------------------------
# TestBrokerFactory
# ---------------------------------------------------------------------------

class TestBrokerFactory:

    def test_get_broker_adapter_zerodha(self):
        from src.brokers.factory import get_broker_adapter
        from src.brokers.zerodha import ZerodhaBroker
        adapter = get_broker_adapter("zerodha")
        assert isinstance(adapter, ZerodhaBroker)

    def test_get_broker_adapter_indmoney(self):
        from src.brokers.factory import get_broker_adapter
        from src.brokers.indmoney import INDmoneyBroker
        adapter = get_broker_adapter("indmoney")
        assert isinstance(adapter, INDmoneyBroker)

    def test_get_broker_adapter_unknown_raises(self):
        from src.brokers.factory import get_broker_adapter
        with pytest.raises(ValueError, match="Unknown broker: foobar"):
            get_broker_adapter("foobar")

    @pytest.mark.anyio
    async def test_get_broker_status_returns_both(self):
        from src.brokers.factory import get_broker_status
        with patch("src.brokers.factory.ZerodhaBroker") as MockZ, \
             patch("src.brokers.factory.INDmoneyBroker") as MockI:
            MockZ.return_value.is_authenticated = AsyncMock(return_value=True)
            MockI.return_value.is_authenticated = AsyncMock(return_value=False)
            status = await get_broker_status()
        assert "zerodha" in status
        assert "indmoney" in status
        assert status["zerodha"]["authenticated"] is True
        assert status["indmoney"]["authenticated"] is False

    @pytest.mark.anyio
    async def test_get_broker_status_handles_exception(self):
        from src.brokers.factory import get_broker_status
        with patch("src.brokers.factory.ZerodhaBroker") as MockZ, \
             patch("src.brokers.factory.INDmoneyBroker") as MockI:
            MockZ.return_value.is_authenticated = AsyncMock(side_effect=Exception("crash"))
            MockI.return_value.is_authenticated = AsyncMock(return_value=True)
            status = await get_broker_status()
        # Exception should result in False, not propagate
        assert status["zerodha"]["authenticated"] is False
        assert status["indmoney"]["authenticated"] is True

    @pytest.mark.anyio
    async def test_get_available_brokers_returns_authenticated_only(self):
        from src.brokers.factory import get_available_brokers
        with patch("src.brokers.factory.ZerodhaBroker") as MockZ, \
             patch("src.brokers.factory.INDmoneyBroker") as MockI:
            MockZ.return_value.is_authenticated = AsyncMock(return_value=True)
            MockI.return_value.is_authenticated = AsyncMock(return_value=False)
            available = await get_available_brokers()
        assert len(available) == 1


# ---------------------------------------------------------------------------
# TestUnifiedTools (tool-layer helpers)
# ---------------------------------------------------------------------------

class TestUnifiedTools:

    @pytest.mark.anyio
    async def test_get_unified_holdings_all_merges(self):
        from src.tools.brokers import _unified
        from src.brokers.models import Holding

        z_holding = Holding("INFY", "NSE", 10, 1400.0, 1500.0, 1000.0, 7.14, "zerodha")
        i_holding = Holding("TCS", "NSE", 5, 3000.0, 3200.0, 1000.0, 6.67, "indmoney")

        with patch("src.tools.brokers.ZerodhaBroker") as MockZ, \
             patch("src.tools.brokers.INDmoneyBroker") as MockI:
            MockZ.return_value.is_authenticated = AsyncMock(return_value=True)
            MockZ.return_value.get_holdings = AsyncMock(return_value=[z_holding])
            MockI.return_value.is_authenticated = AsyncMock(return_value=True)
            MockI.return_value.get_holdings = AsyncMock(return_value=[i_holding])

            result = await _unified("get_holdings", "all")

        data = result["data"]
        assert data["total"] == 2
        symbols = [h["symbol"] for h in data["combined"]]
        assert "INFY" in symbols
        assert "TCS" in symbols

    @pytest.mark.anyio
    async def test_get_unified_holdings_zerodha_only(self):
        from src.tools.brokers import _unified
        from src.brokers.models import Holding

        z_holding = Holding("INFY", "NSE", 10, 1400.0, 1500.0, 1000.0, 7.14, "zerodha")

        with patch("src.tools.brokers.ZerodhaBroker") as MockZ:
            MockZ.return_value.is_authenticated = AsyncMock(return_value=True)
            MockZ.return_value.get_holdings = AsyncMock(return_value=[z_holding])

            result = await _unified("get_holdings", "zerodha")

        data = result["data"]
        assert data["total"] == 1
        assert "indmoney" not in data["brokers"]

    @pytest.mark.anyio
    async def test_unified_when_one_broker_fails_returns_other(self):
        from src.tools.brokers import _unified
        from src.brokers.models import Holding

        z_holding = Holding("RELIANCE", "NSE", 2, 2500.0, 2600.0, 200.0, 4.0, "zerodha")

        with patch("src.tools.brokers.ZerodhaBroker") as MockZ, \
             patch("src.tools.brokers.INDmoneyBroker") as MockI:
            MockZ.return_value.is_authenticated = AsyncMock(return_value=True)
            MockZ.return_value.get_holdings = AsyncMock(return_value=[z_holding])
            # INDmoney unauthenticated — should not block zerodha data
            MockI.return_value.is_authenticated = AsyncMock(return_value=False)

            result = await _unified("get_holdings", "all")

        data = result["data"]
        assert data["total"] == 1
        assert data["brokers"]["zerodha"]["status"] == "ok"
        assert data["brokers"]["indmoney"]["status"] in ("unauthenticated", "not_configured")

    @pytest.mark.anyio
    async def test_unified_funds_indmoney_only(self):
        from src.tools.brokers import _unified
        from src.brokers.models import Fund

        fund = Fund(50000.0, 10000.0, 60000.0, "indmoney")

        with patch("src.tools.brokers.INDmoneyBroker") as MockI:
            MockI.return_value.is_authenticated = AsyncMock(return_value=True)
            MockI.return_value.get_funds = AsyncMock(return_value=[fund])

            result = await _unified("get_funds", "indmoney")

        data = result["data"]
        assert data["total"] == 1
        assert data["combined"][0]["available"] == 50000.0

    @pytest.mark.anyio
    async def test_get_broker_status_tool(self):
        from src.tools.brokers import _unified
        # Just verify _unified doesn't raise for orders
        with patch("src.tools.brokers.ZerodhaBroker") as MockZ, \
             patch("src.tools.brokers.INDmoneyBroker") as MockI:
            MockZ.return_value.is_authenticated = AsyncMock(return_value=False)
            MockI.return_value.is_authenticated = AsyncMock(return_value=False)
            result = await _unified("get_orders", "all")
        assert "data" in result
        assert result["data"]["total"] == 0

    @pytest.mark.anyio
    async def test_indmoney_not_configured_when_no_token(self):
        from src.tools.brokers import _unified
        with patch("src.tools.brokers.ZerodhaBroker") as MockZ, \
             patch("src.tools.brokers.INDmoneyBroker") as MockI, \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INDSTOCKS_TOKEN", None)
            MockZ.return_value.is_authenticated = AsyncMock(return_value=False)
            MockI.return_value.is_authenticated = AsyncMock(return_value=False)
            result = await _unified("get_holdings", "all")
        data = result["data"]
        assert data["brokers"]["indmoney"]["status"] == "not_configured"


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------

class TestModels:

    def test_position_to_dict(self):
        from src.brokers.models import Position
        p = Position("NIFTY", "NFO", "INTRADAY", 50, 120.0, 150.0, 1500.0, "zerodha")
        d = p.to_dict()
        assert d["symbol"] == "NIFTY"
        assert d["product"] == "INTRADAY"
        assert d["broker"] == "zerodha"

    def test_order_to_dict(self):
        from src.brokers.models import Order
        o = Order("ORD1", "TCS", "NSE", "SELL", 10, 3500.0, "COMPLETE", "indmoney")
        d = o.to_dict()
        assert d["order_id"] == "ORD1"
        assert d["status"] == "COMPLETE"

    def test_fund_to_dict(self):
        from src.brokers.models import Fund
        f = Fund(50000.0, 10000.0, 60000.0, "zerodha")
        d = f.to_dict()
        assert d["available"] == 50000.0
        assert d["total"] == 60000.0

    def test_quote_to_dict(self):
        from src.brokers.models import Quote
        q = Quote("INFY", 1600.0, 1580.0, 1620.0, 1570.0, 1590.0, 1000000, "indmoney")
        d = q.to_dict()
        assert d["ltp"] == 1600.0
        assert d["volume"] == 1000000

    def test_holding_pnl_percent_calculation(self):
        """Zerodha adapter calculates pnl_percent correctly."""
        from src.brokers.models import Holding
        h = Holding("TCS", "NSE", 5, 3000.0, 3300.0, 1500.0, 10.0, "zerodha")
        assert h.pnl_percent == 10.0
