"""Phase 23 — order placement core tests.

Covers OrderRequest payload mapping, INDmoneyBroker.place_order (mocked httpx),
security_id resolution, and the submit_order orchestrator. No network calls.
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_httpx_response(status_code: int, json_data=None, text_data: str = ""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = text_data
    return resp


def _async_cm(return_value):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=return_value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _broker(token: str = "test-token"):
    from src.brokers.indmoney import INDmoneyBroker
    with patch.dict(os.environ, {"INDSTOCKS_TOKEN": token}):
        b = INDmoneyBroker()
    b._token = token
    return b


# ---------------------------------------------------------------------------
# OrderRequest.to_indstocks_payload
# ---------------------------------------------------------------------------

class TestOrderRequestPayload:

    def test_limit_order_nse(self):
        from src.brokers.models import OrderRequest
        req = OrderRequest(
            security_id="2885", exchange="nse", segment="equity",
            transaction_type="buy", quantity=10, order_type="limit",
            product="cnc", limit_price=2870.5, symbol="RELIANCE",
        )
        p = req.to_indstocks_payload()
        assert p == {
            "txn_type": "BUY", "exchange": "NSE", "segment": "EQUITY",
            "product": "CNC", "order_type": "LIMIT", "validity": "DAY",
            "security_id": "2885", "qty": 10, "is_amo": False,
            "algo_id": "99999", "limit_price": 2870.5,
        }

    def test_market_order_omits_limit_price(self):
        from src.brokers.models import OrderRequest
        req = OrderRequest(
            security_id="500112", exchange="BSE", segment="EQUITY",
            transaction_type="SELL", quantity=1, order_type="MARKET",
            product="INTRADAY",
        )
        p = req.to_indstocks_payload()
        assert "limit_price" not in p
        assert p["algo_id"] == "9999999999999999"  # BSE
        assert p["txn_type"] == "SELL"
        assert p["order_type"] == "MARKET"

    def test_symbol_is_display_only(self):
        from src.brokers.models import OrderRequest
        req = OrderRequest(
            security_id="1", exchange="NSE", segment="EQUITY",
            transaction_type="BUY", quantity=1, symbol="TCS",
        )
        assert "symbol" not in req.to_indstocks_payload()


# ---------------------------------------------------------------------------
# INDmoneyBroker.place_order
# ---------------------------------------------------------------------------

class TestPlaceOrder:

    def _req(self):
        from src.brokers.models import OrderRequest
        return OrderRequest(
            security_id="2885", exchange="NSE", segment="EQUITY",
            transaction_type="BUY", quantity=1, order_type="MARKET",
            product="INTRADAY", symbol="RELIANCE",
        )

    @pytest.mark.anyio
    async def test_no_token(self):
        from src.brokers.indmoney import INDmoneyBroker
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INDSTOCKS_TOKEN", None)
            b = INDmoneyBroker()
        result = await b.place_order(self._req())
        assert result["status"] == "error"
        assert result["message"] == "not_configured"

    @pytest.mark.anyio
    async def test_success(self):
        b = _broker()
        resp = _make_httpx_response(200, {
            "status": "success",
            "data": {"order_id": "DRV-29301125", "order_status": "O-PENDING"},
        })
        client_mock = MagicMock()
        client_mock.post = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            result = await b.place_order(self._req())
        assert result["status"] == "ok"
        assert result["order_id"] == "DRV-29301125"
        assert result["order_status"] == "O-PENDING"
        # posted to the right endpoint with the mapped payload
        args, kwargs = client_mock.post.call_args
        assert args[0].endswith("/order")
        assert kwargs["json"]["txn_type"] == "BUY"

    @pytest.mark.anyio
    async def test_broker_rejects(self):
        b = _broker()
        resp = _make_httpx_response(400, {"status": "error", "message": "insufficient funds"})
        client_mock = MagicMock()
        client_mock.post = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            result = await b.place_order(self._req())
        assert result["status"] == "error"
        assert result["order_id"] is None
        assert result["status_code"] == 400

    @pytest.mark.anyio
    async def test_2xx_but_not_success_body(self):
        # HTTP 200 but body status != "success" must be treated as error.
        b = _broker()
        resp = _make_httpx_response(200, {"status": "failure", "data": {}})
        client_mock = MagicMock()
        client_mock.post = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            result = await b.place_order(self._req())
        assert result["status"] == "error"

    @pytest.mark.anyio
    async def test_network_exception(self):
        b = _broker()
        client_mock = MagicMock()
        client_mock.post = AsyncMock(side_effect=Exception("timeout"))
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            result = await b.place_order(self._req())
        assert result["status"] == "error"
        assert "timeout" in result["message"]


# ---------------------------------------------------------------------------
# resolve_security_id
# ---------------------------------------------------------------------------

class TestResolveSecurityId:

    @pytest.mark.anyio
    async def test_match_uppercase_headers(self):
        # The real INDstocks CSV uses UPPER_SNAKE_CASE headers (documented schema:
        # SECURITY_ID, TRADING_SYMBOL). Resolution must match those exactly.
        b = _broker()
        rows = [
            {"EXCH": "NSE", "TRADING_SYMBOL": "TCS", "SECURITY_ID": "11536"},
            {"EXCH": "NSE", "TRADING_SYMBOL": "RELIANCE", "SECURITY_ID": "2885"},
        ]
        with patch.object(b, "get_instruments", AsyncMock(return_value=rows)):
            assert await b.resolve_security_id("reliance") == "2885"

    @pytest.mark.anyio
    async def test_match_falls_back_to_symbol_name(self):
        b = _broker()
        rows = [{"SYMBOL_NAME": "INFY", "SECURITY_ID": "1594"}]
        with patch.object(b, "get_instruments", AsyncMock(return_value=rows)):
            assert await b.resolve_security_id("INFY") == "1594"

    @pytest.mark.anyio
    async def test_no_match(self):
        b = _broker()
        with patch.object(b, "get_instruments", AsyncMock(return_value=[{"TRADING_SYMBOL": "TCS", "SECURITY_ID": "1"}])):
            assert await b.resolve_security_id("NOTLISTED") is None

    @pytest.mark.anyio
    async def test_empty_symbol(self):
        b = _broker()
        assert await b.resolve_security_id("") is None

    @pytest.mark.anyio
    async def test_caches_instrument_master(self):
        b = _broker()
        mock_get = AsyncMock(return_value=[{"TRADING_SYMBOL": "TCS", "SECURITY_ID": "1"}])
        with patch.object(b, "get_instruments", mock_get):
            await b.resolve_security_id("TCS")
            await b.resolve_security_id("TCS")
        assert mock_get.call_count == 1  # second call served from cache


# ---------------------------------------------------------------------------
# submit_order orchestrator
# ---------------------------------------------------------------------------

class TestSubmitOrder:

    def _req(self, security_id="2885"):
        from src.brokers.models import OrderRequest
        return OrderRequest(
            security_id=security_id, exchange="NSE", segment="EQUITY",
            transaction_type="BUY", quantity=1, symbol="RELIANCE",
        )

    @pytest.mark.anyio
    async def test_missing_security_id_short_circuits(self):
        from src.execution.service import submit_order
        result = await submit_order(self._req(security_id=""), source="web", user_id="u1")
        assert result["status"] == "error"
        assert "security_id" in result["message"]

    @pytest.mark.anyio
    async def test_places_and_logs(self):
        import src.execution.service as svc
        placed = {"status": "ok", "order_id": "X1", "order_status": "O-PENDING", "body": {}}
        adapter = MagicMock()
        adapter.place_order = AsyncMock(return_value=placed)
        save_mock = AsyncMock(return_value={"id": "row1"})
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(svc._repo, "save_order", save_mock):
            result = await svc.submit_order(self._req(), source="telegram", user_id="u1")
        assert result == placed
        adapter.place_order.assert_awaited_once()
        save_mock.assert_awaited_once()
        assert save_mock.call_args.kwargs["source"] == "telegram"

    @pytest.mark.anyio
    async def test_order_succeeds_even_if_logging_fails(self):
        import src.execution.service as svc
        placed = {"status": "ok", "order_id": "X1", "body": {}}
        adapter = MagicMock()
        adapter.place_order = AsyncMock(return_value=placed)
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(svc._repo, "save_order", AsyncMock(side_effect=Exception("db down"))):
            result = await svc.submit_order(self._req(), source="web", user_id=None)
        assert result["status"] == "ok"  # logging failure did not break the order
