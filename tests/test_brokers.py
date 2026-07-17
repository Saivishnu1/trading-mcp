"""
Phase 1 — Broker Intelligence tests.

Covers: INDmoneyBroker, ZerodhaBroker, factory, and unified tool helpers.
No real network calls — all HTTP and broker interactions are mocked.
"""
from __future__ import annotations

import os
from datetime import datetime

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


@pytest.fixture(autouse=True)
def _clear_instrument_cache():
    """resolve_security_name (like resolve_security_id/search_instruments)
    shares a process-wide TTL cache keyed by source — isolate tests that
    exercise it from each other and from other test files."""
    from src.brokers import indmoney as indmoney_module
    indmoney_module._instrument_cache.clear()
    yield
    indmoney_module._instrument_cache.clear()


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
    async def test_get_holdings_missing_trading_symbol_falls_back_to_resolved_name(self):
        # A same-day-flat holding can omit trading_symbol entirely (2026-07-15
        # bug) — rather than display the bare security_id, look up the real
        # name from the instrument master.
        b = self._broker()
        payload = [
            {
                "security_id": "500325",
                "exchange_segment": "BSE_EQ",
                "quantity": 0,
                "average_price": 0,
                "last_traded_price": 0,
                "pnl_absolute": 0,
                "pnl_percent": 0,
            }
        ]
        resp = _make_httpx_response(200, payload)
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        instrument_rows = [{"SECURITY_ID": "500325", "TRADING_SYMBOL": "RELIANCE"}]
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)), \
             patch.object(b, "get_instruments", AsyncMock(return_value=instrument_rows)):
            holdings = await b.get_holdings()
        assert holdings[0].symbol == "RELIANCE"

    @pytest.mark.anyio
    async def test_get_holdings_missing_trading_symbol_and_unresolvable_falls_back_to_id(self):
        b = self._broker()
        payload = [{
            "security_id": "999999", "exchange_segment": "BSE_EQ", "quantity": 0,
            "average_price": 0, "last_traded_price": 0, "pnl_absolute": 0, "pnl_percent": 0,
        }]
        resp = _make_httpx_response(200, payload)
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)), \
             patch.object(b, "get_instruments", AsyncMock(return_value=[])):
            holdings = await b.get_holdings()
        assert holdings[0].symbol == "999999"

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

    @pytest.mark.anyio
    async def test_get_funds_exposes_segment_breakdown_verbatim(self):
        # Confirmed bug (2026-07-13): "available" under-reported real F&O
        # buying power — segment_breakdown lets a caller see every real key
        # instead of trusting the single option_buy/eq_cnc guess.
        b = self._broker()
        payload = {
            "status": "success",
            "data": {
                "sod_balance": 4996.47,
                "detailed_avl_balance": {
                    "option_buy": 4449.65,
                    "eq_cnc": 2980.40,
                    "some_other_derivative_limit": 15230.0,
                },
                "realized_pnl": -751.92,
            },
        }
        resp = _make_httpx_response(200, payload)
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            funds = await b.get_funds()
        assert funds[0].segment_breakdown == {
            "option_buy": 4449.65, "eq_cnc": 2980.40, "some_other_derivative_limit": 15230.0,
        }

    @pytest.mark.anyio
    async def test_get_funds_segment_param_overrides_default_key(self):
        b = self._broker()
        payload = {
            "status": "success",
            "data": {
                "sod_balance": 4996.47,
                "detailed_avl_balance": {
                    "option_buy": 4449.65,
                    "eq_cnc": 2980.40,
                    "some_other_derivative_limit": 15230.0,
                },
                "realized_pnl": -751.92,
            },
        }
        resp = _make_httpx_response(200, payload)
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            funds = await b.get_funds(segment="some_other_derivative_limit")
        assert funds[0].available == 15230.0

    @pytest.mark.anyio
    async def test_get_funds_unknown_segment_falls_back_to_default_chain(self):
        b = self._broker()
        payload = {
            "status": "success",
            "data": {
                "sod_balance": 4996.47,
                "detailed_avl_balance": {"option_buy": 4449.65, "eq_cnc": 2980.40},
                "realized_pnl": -751.92,
            },
        }
        resp = _make_httpx_response(200, payload)
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            funds = await b.get_funds(segment="does_not_exist")
        assert funds[0].available == 4449.65

    # --- get_positions ---

    @pytest.mark.anyio
    async def test_get_positions_success(self):
        # Real confirmed shape (2026-07-16/17, via get_indmoney_raw_data
        # against an actually-open position): a flat list under "data", with
        # net_qty/avg_price/product — NOT the previously-guessed
        # net_quantity/average_price/exchange_segment/position_type, none of
        # which exist in the real response.
        b = self._broker()
        payload = {
            "status": "success",
            "data": [
                {
                    "net_qty": 65, "avg_price": 44.25, "realized_profit": 0,
                    "exchange": "", "security_id": "57339", "symbol": "NIFTY",
                    "drv_instrument": "OPTIDX", "drv_expiry_date": "07/21/2026 14:00",
                    "drv_option_type": "PE", "drv_strike_price": 23950,
                    "product": "MARGIN",
                }
            ],
        }
        resp = _make_httpx_response(200, payload)
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        instrument_rows = [{
            "SECURITY_ID": "57339", "TRADING_SYMBOL": "NIFTY-JUL2026-23950-PE", "EXCH": "NSE",
        }]
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)), \
             patch.object(b, "get_instruments", AsyncMock(return_value=instrument_rows)):
            positions = await b.get_positions()
        assert len(positions) == 1
        p = positions[0]
        assert p.symbol == "NIFTY-JUL2026-23950-PE"
        assert p.exchange == "NSE"
        assert p.quantity == 65
        assert p.avg_price == 44.25
        assert p.product == "MARGIN"
        assert p.broker == "indmoney"

    @pytest.mark.anyio
    async def test_get_positions_resolves_bse_exchange_when_field_is_empty(self):
        # The confirmed real bug: "exchange" is always "" in practice, so a
        # BSE (SENSEX) position must be resolved via the instrument master,
        # not read directly off the position row.
        b = self._broker()
        payload = {
            "status": "success",
            "data": [{
                "net_qty": 20, "avg_price": 157.25, "realized_profit": 0,
                "exchange": "", "security_id": "824353", "symbol": "SENSEX",
                "drv_instrument": "OPTIDX", "drv_expiry_date": "07/16/2026 14:00",
                "drv_option_type": "CE", "drv_strike_price": 77800, "product": "MARGIN",
            }],
        }
        resp = _make_httpx_response(200, payload)
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        instrument_rows = [{
            "SECURITY_ID": "824353", "TRADING_SYMBOL": "SENSEX 16 JUL 77800 CE", "EXCH": "BSE",
        }]
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)), \
             patch.object(b, "get_instruments", AsyncMock(return_value=instrument_rows)):
            positions = await b.get_positions()
        assert positions[0].exchange == "BSE"
        assert positions[0].quantity == 20

    @pytest.mark.anyio
    async def test_get_positions_missing_trading_symbol_falls_back_to_resolved_name(self):
        # trading_symbol never exists in the real response at all (confirmed
        # 2026-07-16/17), not just for squared-off rows as originally
        # theorized — every row needs the reverse lookup.
        b = self._broker()
        payload = {
            "status": "success",
            "data": [{
                "security_id": "824353", "exchange": "", "net_qty": 0,
                "avg_price": 0, "realized_profit": 0, "symbol": "SENSEX",
            }],
        }
        resp = _make_httpx_response(200, payload)
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        instrument_rows = [{"SECURITY_ID": "824353", "TRADING_SYMBOL": "SENSEX 16 JUL 77800 CE"}]
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)), \
             patch.object(b, "get_instruments", AsyncMock(return_value=instrument_rows)):
            positions = await b.get_positions()
        assert positions[0].symbol == "SENSEX 16 JUL 77800 CE"

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

    @pytest.mark.anyio
    async def test_get_historical_data_unparseable_shape_logs_warning(self, caplog):
        # 2026-07-16 bug: a 200 OK with a non-empty body that doesn't match
        # the assumed [ts, o, h, l, c, v] list-of-lists shape silently
        # produced zero candles (and, before this fix, zero trace of why —
        # the /trade/candles route then reported a misleading 502 with no
        # way to tell it apart from a genuine broker outage).
        import logging
        b = self._broker()
        payload = {"data": [{"time": 1700000000000, "o": 100.0}]}  # not the assumed shape
        resp = _make_httpx_response(200, payload)
        client_mock = MagicMock()
        client_mock.get = AsyncMock(return_value=resp)
        with caplog.at_level(logging.WARNING, logger="src.brokers.indmoney"), \
             patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            candles = await b.get_historical_data("NSE_128673", "1day", "2024-01-01", "2024-01-31")
        assert candles == []
        assert any("parsed 0 candles" in r.message for r in caplog.records)


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
    async def test_get_unified_funds_segment_reaches_indmoney_only(self):
        # Confirmed bug (2026-07-13): under-reported F&O buying power fix —
        # `segment` must reach INDmoneyBroker.get_funds(), and must NOT be
        # passed to Zerodha (whose margins() segment vocabulary is
        # unrelated — "equity"/"commodity", not INDmoney's balance keys).
        from mcp.server.fastmcp import FastMCP as _FastMCP
        from src.tools import brokers as brokers_tools
        from src.brokers.models import Fund

        mcp = _FastMCP("test")
        brokers_tools.register(mcp)
        tools = {t.name: t for t in mcp._tool_manager.list_tools()}

        fund = Fund(available=15230.0, used=0.0, total=15230.0, broker="indmoney")
        with patch("src.tools.brokers.ZerodhaBroker") as MockZ, \
             patch("src.tools.brokers.INDmoneyBroker") as MockI:
            MockZ.return_value.is_authenticated = AsyncMock(return_value=True)
            MockZ.return_value.get_funds = AsyncMock(return_value=[])
            MockI.return_value.is_authenticated = AsyncMock(return_value=True)
            MockI.return_value.get_funds = AsyncMock(return_value=[fund])

            result = await tools["get_unified_funds"].fn(broker="all", segment="some_other_derivative_limit")

            MockI.return_value.get_funds.assert_awaited_once_with(segment="some_other_derivative_limit")
            MockZ.return_value.get_funds.assert_awaited_once_with()

        assert result["data"]["combined"][0]["available"] == 15230.0

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


class TestGetAllOpenPositions:
    """Priority B6 (2026-07-11) — unified positions+holdings across
    Zerodha + INDmoney, all segments including MCX passthrough."""

    def _tools(self):
        from mcp.server.fastmcp import FastMCP as _FastMCP
        from src.tools import brokers as brokers_tools
        mcp = _FastMCP("test")
        brokers_tools.register(mcp)
        return {t.name: t for t in mcp._tool_manager.list_tools()}

    @pytest.mark.anyio
    async def test_combines_positions_and_holdings_across_brokers(self):
        from src.brokers.models import Position, Holding

        z_position = Position("NIFTY24200CE", "NSE", "NRML", 50, 100.0, 120.0, 1000.0, "zerodha")
        i_holding = Holding("TCS", "NSE", 5, 3000.0, 3200.0, 1000.0, 6.67, "indmoney")

        with patch("src.tools.brokers.ZerodhaBroker") as MockZ, \
             patch("src.tools.brokers.INDmoneyBroker") as MockI, \
             patch("src.tools.brokers._sl_target_status_by_symbol", AsyncMock(return_value={})):
            MockZ.return_value.is_authenticated = AsyncMock(return_value=True)
            MockZ.return_value.get_positions = AsyncMock(return_value=[z_position])
            MockZ.return_value.get_holdings = AsyncMock(return_value=[])
            MockI.return_value.is_authenticated = AsyncMock(return_value=True)
            MockI.return_value.get_positions = AsyncMock(return_value=[])
            MockI.return_value.get_holdings = AsyncMock(return_value=[i_holding])

            tools = self._tools()
            result = await tools["get_all_open_positions"].fn()

        symbols = {p["symbol"] for p in result["data"]["positions"]}
        assert symbols == {"NIFTY24200CE", "TCS"}
        assert result["data"]["total"] == 2

    @pytest.mark.anyio
    async def test_nse_position_gets_1530_close_time(self):
        from src.brokers.models import Position

        z_position = Position("INFY", "NSE", "CNC", 10, 1500.0, 1550.0, 500.0, "zerodha")

        with patch("src.tools.brokers.ZerodhaBroker") as MockZ, \
             patch("src.tools.brokers.INDmoneyBroker") as MockI, \
             patch("src.tools.brokers._sl_target_status_by_symbol", AsyncMock(return_value={})):
            MockZ.return_value.is_authenticated = AsyncMock(return_value=True)
            MockZ.return_value.get_positions = AsyncMock(return_value=[z_position])
            MockZ.return_value.get_holdings = AsyncMock(return_value=[])
            MockI.return_value.is_authenticated = AsyncMock(return_value=False)

            tools = self._tools()
            result = await tools["get_all_open_positions"].fn()

        entry = result["data"]["positions"][0]
        assert entry["exchange"] == "NSE"
        assert entry["session_close_time"] == "15:30"

    @pytest.mark.anyio
    async def test_mcx_position_gets_2330_close_time_passthrough(self):
        """No MCX symbol/quote support exists in this platform yet (see
        docs/research/mcx_scope_20260711.md) — but if the broker API ever
        surfaces an MCX row, it must pass through with the correct
        extended-hours close time, not silently default to NSE's 15:30."""
        from src.brokers.models import Position

        mcx_position = Position("NATGASMINI25JULFUT", "MCX", "NRML", 1, 285.0, 290.0, 500.0, "zerodha")

        with patch("src.tools.brokers.ZerodhaBroker") as MockZ, \
             patch("src.tools.brokers.INDmoneyBroker") as MockI, \
             patch("src.tools.brokers._sl_target_status_by_symbol", AsyncMock(return_value={})):
            MockZ.return_value.is_authenticated = AsyncMock(return_value=True)
            MockZ.return_value.get_positions = AsyncMock(return_value=[mcx_position])
            MockZ.return_value.get_holdings = AsyncMock(return_value=[])
            MockI.return_value.is_authenticated = AsyncMock(return_value=False)

            tools = self._tools()
            result = await tools["get_all_open_positions"].fn()

        entry = result["data"]["positions"][0]
        assert entry["exchange"] == "MCX"
        assert entry["session_close_time"] == "23:30"

    @pytest.mark.anyio
    async def test_entry_fields_mapped_correctly(self):
        from src.brokers.models import Position

        z_position = Position("INFY", "NSE", "CNC", 10, 1500.0, 1550.0, 500.0, "zerodha")

        with patch("src.tools.brokers.ZerodhaBroker") as MockZ, \
             patch("src.tools.brokers.INDmoneyBroker") as MockI, \
             patch("src.tools.brokers._sl_target_status_by_symbol", AsyncMock(return_value={})):
            MockZ.return_value.is_authenticated = AsyncMock(return_value=True)
            MockZ.return_value.get_positions = AsyncMock(return_value=[z_position])
            MockZ.return_value.get_holdings = AsyncMock(return_value=[])
            MockI.return_value.is_authenticated = AsyncMock(return_value=False)

            tools = self._tools()
            result = await tools["get_all_open_positions"].fn()

        entry = result["data"]["positions"][0]
        assert entry["entry_price"] == 1500.0
        assert entry["current_price"] == 1550.0
        assert entry["unrealized_pnl"] == 500.0
        assert entry["quantity"] == 10
        assert entry["broker"] == "zerodha"

    @pytest.mark.anyio
    async def test_sl_target_status_best_effort_never_fails_tool(self):
        """Monitor DB unavailable (e.g. no live Postgres in this dev env) —
        the tool must still succeed with sl_status/target_status "unknown"."""
        from src.brokers.models import Position

        z_position = Position("INFY", "NSE", "CNC", 10, 1500.0, 1550.0, 500.0, "zerodha")

        with patch("src.tools.brokers.ZerodhaBroker") as MockZ, \
             patch("src.tools.brokers.INDmoneyBroker") as MockI, \
             patch("src.monitor.repository.MonitorRepository") as MockRepo:
            MockZ.return_value.is_authenticated = AsyncMock(return_value=True)
            MockZ.return_value.get_positions = AsyncMock(return_value=[z_position])
            MockZ.return_value.get_holdings = AsyncMock(return_value=[])
            MockI.return_value.is_authenticated = AsyncMock(return_value=False)
            MockRepo.return_value.get_active_users = AsyncMock(side_effect=RuntimeError("no DB"))

            tools = self._tools()
            result = await tools["get_all_open_positions"].fn()

        entry = result["data"]["positions"][0]
        assert entry["sl_status"] == "unknown"
        assert entry["target_status"] == "unknown"
        assert "error" not in result["data"]
        assert result["data"]["total"] == 1

    @pytest.mark.anyio
    async def test_session_close_risk_flagged_for_untracked_mcx_position_near_close(self):
        """Priority B7 (2026-07-11) — every MCX position is genuinely
        untracked by this monitor's SL system today (no MCX symbol
        resolution exists), so sl_status stays "unknown" and the flag must
        fire when close is imminent."""
        from src.brokers.models import Position

        mcx_position = Position("NATGASMINI25JULFUT", "MCX", "NRML", 1, 285.0, 290.0, 500.0, "indmoney")

        with patch("src.tools.brokers.ZerodhaBroker") as MockZ, \
             patch("src.tools.brokers.INDmoneyBroker") as MockI, \
             patch("src.tools.brokers._sl_target_status_by_symbol", AsyncMock(return_value={})), \
             patch("src.tools.brokers.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 11, 23, 0)
            MockZ.return_value.is_authenticated = AsyncMock(return_value=False)
            MockI.return_value.is_authenticated = AsyncMock(return_value=True)
            MockI.return_value.get_positions = AsyncMock(return_value=[mcx_position])
            MockI.return_value.get_holdings = AsyncMock(return_value=[])

            tools = self._tools()
            result = await tools["get_all_open_positions"].fn()

        entry = result["data"]["positions"][0]
        assert entry["SESSION_CLOSE_RISK"] is not None
        assert "30 minutes" in entry["SESSION_CLOSE_RISK"]

    @pytest.mark.anyio
    async def test_session_close_risk_none_when_not_near_close(self):
        from src.brokers.models import Position

        mcx_position = Position("NATGASMINI25JULFUT", "MCX", "NRML", 1, 285.0, 290.0, 500.0, "indmoney")

        with patch("src.tools.brokers.ZerodhaBroker") as MockZ, \
             patch("src.tools.brokers.INDmoneyBroker") as MockI, \
             patch("src.tools.brokers._sl_target_status_by_symbol", AsyncMock(return_value={})), \
             patch("src.tools.brokers.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 11, 12, 0)
            MockZ.return_value.is_authenticated = AsyncMock(return_value=False)
            MockI.return_value.is_authenticated = AsyncMock(return_value=True)
            MockI.return_value.get_positions = AsyncMock(return_value=[mcx_position])
            MockI.return_value.get_holdings = AsyncMock(return_value=[])

            tools = self._tools()
            result = await tools["get_all_open_positions"].fn()

        entry = result["data"]["positions"][0]
        assert entry["SESSION_CLOSE_RISK"] is None

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
