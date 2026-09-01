"""Phase 23 — order placement core tests.

Covers OrderRequest payload mapping, INDmoneyBroker.place_order (mocked httpx),
security_id resolution, and the submit_order orchestrator. No network calls.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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


@pytest.fixture(autouse=True)
def _clear_instrument_cache():
    """resolve_security_id/search_instruments share a process-wide TTL cache
    (see src/brokers/indmoney.py) so results from one test don't leak into
    the next via a shared "equity"/"fno" cache key."""
    from src.brokers import indmoney as indmoney_module
    indmoney_module._instrument_cache.clear()
    yield
    indmoney_module._instrument_cache.clear()


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

    def test_is_smart_order_false_without_legs(self):
        from src.brokers.models import OrderRequest
        req = OrderRequest(security_id="1", exchange="NSE", segment="EQUITY",
                            transaction_type="BUY", quantity=1)
        assert not req.is_smart_order

    def test_is_smart_order_true_with_sl(self):
        from src.brokers.models import OrderRequest
        req = OrderRequest(security_id="1", exchange="NSE", segment="EQUITY",
                            transaction_type="BUY", quantity=1, sl_trigger_price=2820.0)
        assert req.is_smart_order

    def test_smart_order_payload_includes_sl_and_target_legs(self):
        from src.brokers.models import OrderRequest
        req = OrderRequest(
            security_id="2885", exchange="NSE", segment="EQUITY",
            transaction_type="BUY", quantity=1, order_type="LIMIT", limit_price=2870.0,
            sl_trigger_price=2820.0, sl_limit_price=2810.0,
            tgt_trigger_price=2950.0, tgt_limit_price=2950.0,
        )
        p = req.to_indstocks_smart_order_payload()
        assert p["sl_trigger_price"] == 2820.0
        assert p["sl_limit_price"] == 2810.0
        assert p["tgt_trigger_price"] == 2950.0
        assert p["tgt_limit_price"] == 2950.0
        assert p["limit_price"] == 2870.0
        assert "trailing_sl_points" not in p  # never sent to INDstocks — client-side only

    def test_smart_order_payload_omits_unset_legs(self):
        from src.brokers.models import OrderRequest
        req = OrderRequest(security_id="1", exchange="NSE", segment="EQUITY",
                            transaction_type="BUY", quantity=1, sl_trigger_price=2820.0)
        p = req.to_indstocks_smart_order_payload()
        assert "sl_trigger_price" in p
        assert "tgt_trigger_price" not in p
        assert "sl_limit_price" not in p


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
        # 2026-07-16 bug: a clean rejection carried no "message" field at all,
        # so the web UI's error banner had nothing to show the user.
        assert result["message"] == "insufficient funds"

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
# INDmoneyBroker smart orders (SL/target legs)
# ---------------------------------------------------------------------------

class TestSmartOrder:

    def _smart_req(self):
        from src.brokers.models import OrderRequest
        return OrderRequest(
            security_id="2885", exchange="NSE", segment="EQUITY",
            transaction_type="BUY", quantity=1, order_type="MARKET",
            product="INTRADAY", symbol="RELIANCE",
            sl_trigger_price=2820.0, sl_limit_price=2810.0,
            tgt_trigger_price=2950.0, tgt_limit_price=2950.0,
        )

    @pytest.mark.anyio
    async def test_place_order_routes_smart_orders_to_smart_endpoint(self):
        b = _broker()
        resp = _make_httpx_response(200, {
            "status": "success",
            "data": {"order_data": [{
                "order_id": "DRV-1", "order_status": "CREATED",
                "child_order_details": {"order_id": "GTT-1", "order_status": "CREATED"},
            }]},
        })
        client_mock = MagicMock()
        client_mock.post = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            result = await b.place_order(self._smart_req())
        assert result["status"] == "ok"
        assert result["order_id"] == "DRV-1"
        assert result["child_order_id"] == "GTT-1"
        args, kwargs = client_mock.post.call_args
        assert args[0].endswith("/smart/order")
        assert kwargs["json"]["sl_trigger_price"] == 2820.0
        assert kwargs["json"]["tgt_trigger_price"] == 2950.0

    @pytest.mark.anyio
    async def test_plain_order_does_not_hit_smart_endpoint(self):
        b = _broker()
        resp = _make_httpx_response(200, {"status": "success", "data": {"order_id": "X", "order_status": "O"}})
        client_mock = MagicMock()
        client_mock.post = AsyncMock(return_value=resp)
        from src.brokers.models import OrderRequest
        plain_req = OrderRequest(security_id="1", exchange="NSE", segment="EQUITY",
                                  transaction_type="BUY", quantity=1)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            await b.place_order(plain_req)
        args, _ = client_mock.post.call_args
        assert args[0].endswith("/order")
        assert not args[0].endswith("/smart/order")

    @pytest.mark.anyio
    async def test_smart_order_rejection(self):
        b = _broker()
        resp = _make_httpx_response(400, {"status": "error", "message": "invalid trigger"})
        client_mock = MagicMock()
        client_mock.post = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            result = await b.place_order(self._smart_req())
        assert result["status"] == "error"
        assert result["order_id"] is None
        # 2026-07-16 bug: _place_smart_order's rejection branch populated
        # neither "message" (UI has nothing to show) nor a log line (server
        # logs had zero trace of why a smart order was rejected).
        assert result["message"] == "invalid trigger"

    @pytest.mark.anyio
    async def test_smart_order_rejection_logs_the_response_body(self, caplog):
        import logging
        b = _broker()
        resp = _make_httpx_response(400, {"status": "error", "message": "invalid trigger"})
        client_mock = MagicMock()
        client_mock.post = AsyncMock(return_value=resp)
        with caplog.at_level(logging.WARNING, logger="src.brokers.indmoney"), \
             patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            await b.place_order(self._smart_req())
        assert any("rejected" in r.message and "invalid trigger" in r.message for r in caplog.records)

    @pytest.mark.anyio
    async def test_modify_smart_order_success(self):
        b = _broker()
        resp = _make_httpx_response(200, {"status": "success", "data": {}})
        client_mock = MagicMock()
        client_mock.post = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            result = await b.modify_smart_order("GTT-1", sl_trigger_price=2830.0, sl_limit_price=2825.0)
        assert result["status"] == "ok"
        args, kwargs = client_mock.post.call_args
        assert args[0].endswith("/smart/order/modify")
        assert kwargs["json"]["order_id"] == "GTT-1"
        assert kwargs["json"]["sl_trigger_price"] == 2830.0

    @pytest.mark.anyio
    async def test_modify_smart_order_no_token(self):
        from src.brokers.indmoney import INDmoneyBroker
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INDSTOCKS_TOKEN", None)
            b = INDmoneyBroker()
        result = await b.modify_smart_order("GTT-1", sl_trigger_price=2830.0)
        assert result["status"] == "error"

    @pytest.mark.anyio
    async def test_cancel_smart_order_success(self):
        b = _broker()
        resp = _make_httpx_response(200, {"status": "success", "data": {}})
        client_mock = MagicMock()
        client_mock.post = AsyncMock(return_value=resp)
        with patch("src.brokers.indmoney.httpx.AsyncClient", return_value=_async_cm(client_mock)):
            result = await b.cancel_smart_order("GTT-1")
        assert result["status"] == "ok"
        args, kwargs = client_mock.post.call_args
        assert args[0].endswith("/smart/order/cancel")
        assert kwargs["json"]["order_id"] == "GTT-1"


# ---------------------------------------------------------------------------
# INDmoneyBroker._extract_error_message (2026-07-16)
# ---------------------------------------------------------------------------

class TestExtractErrorMessage:

    def test_prefers_message_key(self):
        from src.brokers.indmoney import INDmoneyBroker
        assert INDmoneyBroker._extract_error_message(
            {"message": "insufficient funds", "error": "ignored"}
        ) == "insufficient funds"

    def test_falls_back_through_known_keys_in_order(self):
        from src.brokers.indmoney import INDmoneyBroker
        assert INDmoneyBroker._extract_error_message({"error": "bad request"}) == "bad request"
        assert INDmoneyBroker._extract_error_message({"errors": ["a", "b"]}) == "['a', 'b']"
        assert INDmoneyBroker._extract_error_message({"reason": "expired token"}) == "expired token"
        assert INDmoneyBroker._extract_error_message({"detail": "not found"}) == "not found"

    def test_dict_with_no_known_keys_stringifies_whole_body(self):
        from src.brokers.indmoney import INDmoneyBroker
        body = {"status": "error", "code": 42}
        assert INDmoneyBroker._extract_error_message(body) == str(body)

    def test_string_body(self):
        from src.brokers.indmoney import INDmoneyBroker
        assert INDmoneyBroker._extract_error_message("Internal Server Error") == "Internal Server Error"

    def test_empty_body_returns_generic_message(self):
        from src.brokers.indmoney import INDmoneyBroker
        assert INDmoneyBroker._extract_error_message(None) == "Order rejected by broker."
        assert INDmoneyBroker._extract_error_message("") == "Order rejected by broker."
        assert INDmoneyBroker._extract_error_message({}) == "Order rejected by broker."


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
    async def test_exchange_filter_picks_matching_row_for_dual_listed_symbol(self):
        # Same TRADING_SYMBOL listed on both NSE and BSE with different
        # security_ids — without an exchange filter this used to always
        # return whichever row came first (2026-07-15 bug: broke live
        # pricing for BSE positions since the wrong security_id was used
        # to build the WebSocket instrument key).
        b = _broker()
        rows = [
            {"EXCH": "NSE", "TRADING_SYMBOL": "RELIANCE", "SECURITY_ID": "2885"},
            {"EXCH": "BSE", "TRADING_SYMBOL": "RELIANCE", "SECURITY_ID": "500325"},
        ]
        with patch.object(b, "get_instruments", AsyncMock(return_value=rows)):
            assert await b.resolve_security_id("RELIANCE", exchange="BSE") == "500325"
            assert await b.resolve_security_id("RELIANCE", exchange="NSE") == "2885"
            # No exchange hint at all — preserves prior first-match behavior.
            assert await b.resolve_security_id("RELIANCE") == "2885"

    @pytest.mark.anyio
    async def test_exchange_filter_falls_back_when_no_row_matches(self):
        # Requested exchange isn't present at all (or EXCH uses an
        # unexpected string) — fall back to the first symbol-text match
        # rather than returning None outright.
        b = _broker()
        rows = [{"EXCH": "NSE", "TRADING_SYMBOL": "TCS", "SECURITY_ID": "11536"}]
        with patch.object(b, "get_instruments", AsyncMock(return_value=rows)):
            assert await b.resolve_security_id("TCS", exchange="BSE") == "11536"


class TestResolveSecurityIdStrict:
    """Audit-H3 — resolve_security_id_strict reports whether the match was
    a genuine same-exchange match, so an order-placement caller can refuse
    a wrong-exchange fallback instead of silently accepting it."""

    @pytest.mark.anyio
    async def test_exact_exchange_match_reports_true(self):
        b = _broker()
        rows = [
            {"EXCH": "NSE", "TRADING_SYMBOL": "RELIANCE", "SECURITY_ID": "2885"},
            {"EXCH": "BSE", "TRADING_SYMBOL": "RELIANCE", "SECURITY_ID": "500325"},
        ]
        with patch.object(b, "get_instruments", AsyncMock(return_value=rows)):
            sec_id, matched = await b.resolve_security_id_strict("RELIANCE", exchange="BSE")
        assert sec_id == "500325"
        assert matched is True

    @pytest.mark.anyio
    async def test_fallback_to_other_exchange_reports_false(self):
        b = _broker()
        rows = [{"EXCH": "NSE", "TRADING_SYMBOL": "TCS", "SECURITY_ID": "11536"}]
        with patch.object(b, "get_instruments", AsyncMock(return_value=rows)):
            sec_id, matched = await b.resolve_security_id_strict("TCS", exchange="BSE")
        assert sec_id == "11536"
        assert matched is False

    @pytest.mark.anyio
    async def test_no_exchange_requested_reports_true(self):
        b = _broker()
        rows = [{"EXCH": "NSE", "TRADING_SYMBOL": "TCS", "SECURITY_ID": "11536"}]
        with patch.object(b, "get_instruments", AsyncMock(return_value=rows)):
            sec_id, matched = await b.resolve_security_id_strict("TCS")
        assert sec_id == "11536"
        assert matched is True

    @pytest.mark.anyio
    async def test_no_match_at_all_returns_none_id(self):
        # Nothing found for this symbol at all — resolve_symbol's caller
        # sees security_id is None and reports "symbol not found" (its
        # `if not sec_id` branch), not the wrong-exchange warning path,
        # since that only fires when security_id is not None.
        b = _broker()
        with patch.object(b, "get_instruments", AsyncMock(return_value=[])):
            sec_id, matched = await b.resolve_security_id_strict("NOTLISTED", exchange="BSE")
        assert sec_id is None


# ---------------------------------------------------------------------------
# resolve_security_name (2026-07-15) — reverse of resolve_security_id, used
# when INDstocks omits trading_symbol on a squared-off position/holding.
# ---------------------------------------------------------------------------

class TestResolveSecurityName:

    @pytest.mark.anyio
    async def test_resolves_name_from_matching_source(self):
        b = _broker()
        rows = [{"SECURITY_ID": "824353", "TRADING_SYMBOL": "SENSEX 16 JUL 77800 CE"}]
        with patch.object(b, "get_instruments", AsyncMock(return_value=rows)):
            assert await b.resolve_security_name("824353", source="fno") == "SENSEX 16 JUL 77800 CE"

    @pytest.mark.anyio
    async def test_falls_back_to_other_source_if_not_found(self):
        # A holding might actually be an fno security_id or vice versa —
        # try the other instrument master before giving up.
        b = _broker()
        async def fake_get_instruments(source):
            if source == "fno":
                return [{"SECURITY_ID": "500325", "TRADING_SYMBOL": "RELIANCE-EQ"}]
            return []
        with patch.object(b, "get_instruments", AsyncMock(side_effect=fake_get_instruments)):
            assert await b.resolve_security_name("500325", source="equity") == "RELIANCE-EQ"

    @pytest.mark.anyio
    async def test_returns_none_when_not_found_anywhere(self):
        b = _broker()
        with patch.object(b, "get_instruments", AsyncMock(return_value=[])):
            assert await b.resolve_security_name("000000", source="equity") is None

    @pytest.mark.anyio
    async def test_empty_security_id(self):
        b = _broker()
        assert await b.resolve_security_name("") is None

    @pytest.mark.anyio
    async def test_caches_instrument_master(self):
        from src.brokers import indmoney as indmoney_module
        indmoney_module._instrument_cache.clear()  # isolate from other tests/process cache
        b = _broker()
        mock_get = AsyncMock(return_value=[{"TRADING_SYMBOL": "TCS", "SECURITY_ID": "1"}])
        with patch.object(b, "get_instruments", mock_get):
            await b.resolve_security_id("TCS")
            await b.resolve_security_id("TCS")
        assert mock_get.call_count == 1  # second call served from the process-wide cache
        indmoney_module._instrument_cache.clear()

    @pytest.mark.anyio
    async def test_cache_shared_across_instances(self):
        # The cache is module-level (not per-INDmoneyBroker instance) since a
        # fresh adapter is constructed on every request via get_broker_adapter.
        from src.brokers import indmoney as indmoney_module
        indmoney_module._instrument_cache.clear()
        b1 = _broker()
        mock_get = AsyncMock(return_value=[{"TRADING_SYMBOL": "TCS", "SECURITY_ID": "1"}])
        with patch.object(b1, "get_instruments", mock_get):
            await b1.resolve_security_id("TCS")
        b2 = _broker()  # a brand-new instance, as get_broker_adapter would create
        with patch.object(b2, "get_instruments", AsyncMock(side_effect=AssertionError("should not refetch"))):
            assert await b2.resolve_security_id("TCS") == "1"
        indmoney_module._instrument_cache.clear()

    @pytest.mark.anyio
    async def test_warm_instrument_cache_fetches_both_sources_concurrently(self):
        # Startup pre-warm (server.py / telegram_admin/main.py) must not
        # serialize the two source fetches — that would defeat the purpose
        # of warming ahead of the user's first search.
        import asyncio
        import time

        from src.brokers import indmoney as indmoney_module
        indmoney_module._instrument_cache.clear()
        b = _broker()

        async def slow_get(source):
            await asyncio.sleep(0.1)
            return [{"TRADING_SYMBOL": source.upper(), "SECURITY_ID": "1"}]

        with patch.object(b, "get_instruments", slow_get):
            start = time.monotonic()
            await b.warm_instrument_cache()
            elapsed = time.monotonic() - start
        assert elapsed < 0.17
        assert "equity" in indmoney_module._instrument_cache
        assert "fno" in indmoney_module._instrument_cache
        indmoney_module._instrument_cache.clear()


# ---------------------------------------------------------------------------
# resolve_security_exchange (2026-07-17) — confirmed via get_indmoney_raw_data
# that a position row's own "exchange" field is always empty in practice.
# ---------------------------------------------------------------------------

class TestResolveSecurityExchange:

    @pytest.mark.anyio
    async def test_resolves_exchange_from_matching_source(self):
        b = _broker()
        rows = [{"SECURITY_ID": "824353", "EXCH": "BSE"}]
        with patch.object(b, "get_instruments", AsyncMock(return_value=rows)):
            assert await b.resolve_security_exchange("824353", source="fno") == "BSE"

    @pytest.mark.anyio
    async def test_falls_back_to_other_source_if_not_found(self):
        b = _broker()
        async def fake_get_instruments(source):
            if source == "fno":
                return [{"SECURITY_ID": "500325", "EXCH": "NSE"}]
            return []
        with patch.object(b, "get_instruments", AsyncMock(side_effect=fake_get_instruments)):
            assert await b.resolve_security_exchange("500325", source="equity") == "NSE"

    @pytest.mark.anyio
    async def test_returns_none_when_not_found_anywhere(self):
        b = _broker()
        with patch.object(b, "get_instruments", AsyncMock(return_value=[])):
            assert await b.resolve_security_exchange("000000", source="equity") is None

    @pytest.mark.anyio
    async def test_empty_security_id(self):
        b = _broker()
        assert await b.resolve_security_exchange("") is None


# ---------------------------------------------------------------------------
# search_instruments (broker) / search_symbols (execution service)
# ---------------------------------------------------------------------------

class TestSearchInstruments:

    @pytest.mark.anyio
    async def test_prefix_matches_rank_first(self):
        from src.brokers import indmoney as indmoney_module
        indmoney_module._instrument_cache.clear()
        b = _broker()
        rows = [
            {"EXCH": "NSE", "TRADING_SYMBOL": "IRELIANCEX", "INSTRUMENT_NAME": "Fake Contains Match", "SECURITY_ID": "9"},
            {"EXCH": "NSE", "TRADING_SYMBOL": "RELIANCE", "INSTRUMENT_NAME": "Reliance Industries", "SECURITY_ID": "2885"},
        ]
        with patch.object(b, "get_instruments", AsyncMock(return_value=rows)):
            results = await b.search_instruments("RELIANCE")
        assert [r["symbol"] for r in results] == ["RELIANCE", "IRELIANCEX"]
        # security_id IS included (and must be correct) — the picker needs it
        # to identify one exact contract among same-named weekly options.
        assert results[0]["security_id"] == "2885"
        indmoney_module._instrument_cache.clear()

    @pytest.mark.anyio
    async def test_case_insensitive_and_limit(self):
        from src.brokers import indmoney as indmoney_module
        indmoney_module._instrument_cache.clear()
        b = _broker()
        rows = [{"EXCH": "NSE", "TRADING_SYMBOL": f"SYM{i}TEST", "SECURITY_ID": str(i)} for i in range(20)]
        with patch.object(b, "get_instruments", AsyncMock(return_value=rows)):
            results = await b.search_instruments("test", limit=5)
        assert len(results) == 5
        indmoney_module._instrument_cache.clear()

    @pytest.mark.anyio
    async def test_empty_query_returns_nothing(self):
        b = _broker()
        assert await b.search_instruments("") == []

    @pytest.mark.anyio
    async def test_no_duplicate_symbols(self):
        from src.brokers import indmoney as indmoney_module
        indmoney_module._instrument_cache.clear()
        b = _broker()
        rows = [
            {"EXCH": "NSE", "TRADING_SYMBOL": "TCS", "SECURITY_ID": "1"},
            {"EXCH": "NSE", "TRADING_SYMBOL": "TCS", "SECURITY_ID": "1"},  # dup row
        ]
        with patch.object(b, "get_instruments", AsyncMock(return_value=rows)):
            results = await b.search_instruments("TCS")
        assert len(results) == 1
        indmoney_module._instrument_cache.clear()

    @pytest.mark.anyio
    async def test_same_display_symbol_different_expiries_not_collapsed(self):
        # Regression: INDstocks renders TRADING_SYMBOL month-granular for index
        # options ("NIFTY-JUL2026-27500-PE" for every Thursday in July), so
        # deduping by that string alone silently dropped every weekly contract
        # but the first — the bug behind "only months showing, no days" in the
        # /trade dropdown. Rows differ only by SECURITY_ID/EXPIRY_DATE and must
        # all survive.
        from src.brokers import indmoney as indmoney_module
        indmoney_module._instrument_cache.clear()
        b = _broker()
        rows = [
            {"EXCH": "NSE", "TRADING_SYMBOL": "NIFTY-JUL2026-27500-PE",
             "SECURITY_ID": "111", "EXPIRY_DATE": "2026-07-02"},
            {"EXCH": "NSE", "TRADING_SYMBOL": "NIFTY-JUL2026-27500-PE",
             "SECURITY_ID": "222", "EXPIRY_DATE": "2026-07-09"},
            {"EXCH": "NSE", "TRADING_SYMBOL": "NIFTY-JUL2026-27500-PE",
             "SECURITY_ID": "333", "EXPIRY_DATE": "2026-07-16"},
        ]
        with patch.object(b, "get_instruments", AsyncMock(return_value=rows)):
            results = await b.search_instruments("27500")
        assert len(results) == 3
        assert {r["security_id"] for r in results} == {"111", "222", "333"}
        assert {r["expiry"] for r in results} == {"2026-07-02", "2026-07-09", "2026-07-16"}
        # Ordered chronologically by expiry within the same symbol name.
        assert [r["expiry"] for r in results] == ["2026-07-02", "2026-07-09", "2026-07-16"]
        indmoney_module._instrument_cache.clear()

    @pytest.mark.anyio
    async def test_lot_size_parsed_from_lot_units_column(self):
        # Confirmed 2026-07-12 against a real INDstocks instrument-master row
        # (SENSEX PE: 'LOT_UNITS': '20', matching the exchange-published lot
        # size exactly) — this is real per-contract data from the CSV, not a
        # guessed/hardcoded table (see the segment-misclassification bug this
        # session already hit once from guessing a field's behavior).
        from src.brokers import indmoney as indmoney_module
        indmoney_module._instrument_cache.clear()
        b = _broker()
        rows = [
            {"EXCH": "BSE", "TRADING_SYMBOL": "SENSEX-24Sep2026-87000-PE",
             "SECURITY_ID": "1129411", "LOT_UNITS": "20"},
        ]
        with patch.object(b, "get_instruments", AsyncMock(return_value=rows)):
            results = await b.search_instruments("87000")
        assert results[0]["lot_size"] == 20
        indmoney_module._instrument_cache.clear()

    @pytest.mark.anyio
    async def test_lot_size_none_when_lot_units_missing(self):
        # Equity rows have no lot concept — LOT_UNITS is absent, and the UI
        # must fall back to raw share quantity rather than erroring.
        from src.brokers import indmoney as indmoney_module
        indmoney_module._instrument_cache.clear()
        b = _broker()
        rows = [{"EXCH": "NSE", "TRADING_SYMBOL": "RELIANCE", "SECURITY_ID": "2885"}]
        with patch.object(b, "get_instruments", AsyncMock(return_value=rows)):
            results = await b.search_instruments("RELIANCE")
        assert results[0]["lot_size"] is None
        indmoney_module._instrument_cache.clear()

    @pytest.mark.anyio
    async def test_resolve_security_id_still_returns_a_result_for_ambiguous_symbol(self):
        # resolve_security_id (symbol-text based, used by the Telegram /buy
        # /sell flow which has no picker) is documented as best-effort/
        # ambiguous for these — it must not crash or return None just because
        # multiple rows share a TRADING_SYMBOL.
        from src.brokers import indmoney as indmoney_module
        indmoney_module._instrument_cache.clear()
        b = _broker()
        rows = [
            {"EXCH": "NSE", "TRADING_SYMBOL": "NIFTY-JUL2026-27500-PE", "SECURITY_ID": "111"},
            {"EXCH": "NSE", "TRADING_SYMBOL": "NIFTY-JUL2026-27500-PE", "SECURITY_ID": "222"},
        ]
        with patch.object(b, "get_instruments", AsyncMock(return_value=rows)):
            result = await b.resolve_security_id("NIFTY-JUL2026-27500-PE", source="fno")
        assert result in ("111", "222")
        indmoney_module._instrument_cache.clear()


class TestSearchSymbols:

    @pytest.mark.anyio
    async def test_merges_equity_and_fno_when_no_segment(self):
        import src.execution.service as svc
        adapter = MagicMock()

        async def fake_search(query, source="equity", limit=15):
            if source == "equity":
                return [{"symbol": "RELIANCE", "name": "Reliance Industries", "exchange": "NSE", "segment": ""}]
            return [{"symbol": "NIFTY24200CE", "name": "NIFTY", "exchange": "NSE", "segment": ""}]

        adapter.search_instruments = fake_search
        with patch.object(svc, "get_broker_adapter", return_value=adapter):
            results = await svc.search_symbols("ni")
        segments = {r["segment"] for r in results}
        assert "EQUITY" in segments or "DERIVATIVE" in segments
        assert len(results) == 2

    @pytest.mark.anyio
    async def test_lot_size_passed_through_from_broker_row(self):
        # search_symbols no longer computes lot_size itself — it's real
        # per-contract data already attached by
        # INDmoneyBroker.search_instruments (from the CSV's LOT_UNITS
        # column), just passed through here.
        import src.execution.service as svc
        adapter = MagicMock()

        async def fake_search(query, source="equity", limit=15):
            return [{"symbol": "SENSEX-24Sep2026-87000-PE", "name": "SENSEX",
                      "exchange": "BSE", "segment": "", "lot_size": 20}]

        adapter.search_instruments = fake_search
        with patch.object(svc, "get_broker_adapter", return_value=adapter):
            results = await svc.search_symbols("87000", segment="DERIVATIVE")
        assert results[0]["lot_size"] == 20

    @pytest.mark.anyio
    async def test_dedup_keys_on_security_id_not_symbol_text(self):
        # Same symbol string, different security_id (e.g. two weekly NIFTY
        # contracts returned from different sources by coincidence) must NOT
        # be collapsed — only a genuinely identical security_id should dedup.
        import src.execution.service as svc
        adapter = MagicMock()

        async def fake_search(query, source="equity", limit=15):
            if source == "equity":
                return [{"symbol": "NIFTY-JUL2026-27500-PE", "name": "", "exchange": "NSE",
                          "segment": "", "security_id": "111", "expiry": "2026-07-02"}]
            return [{"symbol": "NIFTY-JUL2026-27500-PE", "name": "", "exchange": "NSE",
                      "segment": "", "security_id": "222", "expiry": "2026-07-09"}]

        adapter.search_instruments = fake_search
        with patch.object(svc, "get_broker_adapter", return_value=adapter):
            results = await svc.search_symbols("27500")
        assert len(results) == 2
        assert {r["security_id"] for r in results} == {"111", "222"}

    @pytest.mark.anyio
    async def test_segment_hint_restricts_to_one_source(self):
        import src.execution.service as svc
        adapter = MagicMock()
        called_sources = []

        async def fake_search(query, source="equity", limit=15):
            called_sources.append(source)
            return []

        adapter.search_instruments = fake_search
        with patch.object(svc, "get_broker_adapter", return_value=adapter):
            await svc.search_symbols("nifty", segment="DERIVATIVE")
        assert called_sources == ["fno"]

    @pytest.mark.anyio
    async def test_equity_and_fno_searched_concurrently_not_sequentially(self):
        # Perf regression guard: without a segment hint, equity+fno must run
        # via asyncio.gather (concurrently), not one `await` after another —
        # on a cold instrument-cache this was the dominant cost of a "slow"
        # search (two ~sequential CSV downloads instead of one wall-clock wait).
        import asyncio
        import time

        import src.execution.service as svc
        adapter = MagicMock()

        async def slow_search(query, source="equity", limit=15):
            await asyncio.sleep(0.1)
            return [{"symbol": source.upper(), "name": "", "exchange": "NSE", "segment": ""}]

        adapter.search_instruments = slow_search
        with patch.object(svc, "get_broker_adapter", return_value=adapter):
            start = time.monotonic()
            await svc.search_symbols("test")
            elapsed = time.monotonic() - start
        # Sequential would take ~0.2s; concurrent should take ~0.1s. Generous
        # threshold to avoid CI flakiness while still catching a regression
        # to sequential awaits.
        assert elapsed < 0.17, f"search_symbols took {elapsed:.3f}s — sources may be running sequentially"


# ---------------------------------------------------------------------------
# resolve_symbol (2026-07-15) — exchange threading through to
# resolve_security_id, end to end (no mocking resolve_security_id itself).
# ---------------------------------------------------------------------------

class TestResolveSymbolExchangeThreading:

    @pytest.mark.anyio
    async def test_bse_position_resolves_bse_security_id_not_nse(self):
        import src.execution.service as svc
        rows = [
            {"EXCH": "NSE", "TRADING_SYMBOL": "RELIANCE", "SECURITY_ID": "2885"},
            {"EXCH": "BSE", "TRADING_SYMBOL": "RELIANCE", "SECURITY_ID": "500325"},
        ]
        adapter = _broker()
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(adapter, "get_instruments", AsyncMock(return_value=rows)):
            result = await svc.resolve_symbol("RELIANCE", exchange="BSE", segment="EQUITY")
        assert result == "500325"

    @pytest.mark.anyio
    async def test_nse_position_still_resolves_nse_security_id(self):
        import src.execution.service as svc
        rows = [
            {"EXCH": "NSE", "TRADING_SYMBOL": "RELIANCE", "SECURITY_ID": "2885"},
            {"EXCH": "BSE", "TRADING_SYMBOL": "RELIANCE", "SECURITY_ID": "500325"},
        ]
        adapter = _broker()
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(adapter, "get_instruments", AsyncMock(return_value=rows)):
            result = await svc.resolve_symbol("RELIANCE", exchange="NSE", segment="EQUITY")
        assert result == "2885"

    @pytest.mark.anyio
    async def test_audit_h3_refuses_wrong_exchange_fallback_for_order_placement(self):
        # Audit-H3: only an NSE row exists for this symbol, but the caller
        # (order placement) explicitly requested BSE. resolve_security_id's
        # best-effort fallback would silently hand back the NSE security_id
        # (documented/intentional for the Telegram symbol-only /buy flow —
        # see TestResolveSecurityId::test_exchange_filter_falls_back_when_no_row_matches
        # in this same test module) — but resolve_symbol, used at the
        # order-submission boundary, must refuse rather than let an order
        # silently route onto the wrong exchange's security_id.
        import src.execution.service as svc
        rows = [{"EXCH": "NSE", "TRADING_SYMBOL": "TCS", "SECURITY_ID": "11536"}]
        adapter = _broker()
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(adapter, "get_instruments", AsyncMock(return_value=rows)):
            result = await svc.resolve_symbol("TCS", exchange="BSE", segment="EQUITY")
        assert result is None

    @pytest.mark.anyio
    async def test_audit_h3_resolve_security_id_fallback_still_intact(self):
        # The underlying resolve_security_id (used by the Telegram /buy /sell
        # symbol-only flow, which has no exchange-aware picker) must keep its
        # documented best-effort fallback — only the stricter order-placement
        # boundary (resolve_symbol) rejects a wrong-exchange match.
        adapter = _broker()
        rows = [{"EXCH": "NSE", "TRADING_SYMBOL": "TCS", "SECURITY_ID": "11536"}]
        with patch.object(adapter, "get_instruments", AsyncMock(return_value=rows)):
            result = await adapter.resolve_security_id("TCS", exchange="BSE")
        assert result == "11536"


# ---------------------------------------------------------------------------
# get_positions_for_web (2026-07-12)
# ---------------------------------------------------------------------------

class TestGetPositionsForWeb:

    def _position(self, symbol="RELIANCE", exchange="NSE", quantity=1, avg=2800.0, ltp=2850.0,
                  pnl=50.0, security_id=None):
        from src.brokers.models import Position
        return Position(symbol=symbol, exchange=exchange, product="INTRADAY",
                         quantity=quantity, avg_price=avg, current_price=ltp, pnl=pnl, broker="indmoney",
                         security_id=security_id)

    def _holding(self, symbol="TCS", exchange="NSE", quantity=5, avg=3500.0, ltp=3600.0, pnl=500.0,
                 security_id=None):
        from src.brokers.models import Holding
        return Holding(symbol=symbol, exchange=exchange, quantity=quantity, avg_price=avg,
                        current_price=ltp, pnl=pnl, pnl_percent=2.85, broker="indmoney",
                        security_id=security_id)

    @pytest.mark.anyio
    async def test_combines_positions_and_holdings(self):
        import src.execution.service as svc
        adapter = MagicMock()
        adapter.get_positions = AsyncMock(return_value=[self._position()])
        adapter.get_holdings = AsyncMock(return_value=[self._holding()])
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(svc, "resolve_symbol", AsyncMock(return_value="2885")), \
             patch.object(svc._repo, "find_active_smart_order_for_symbol", AsyncMock(return_value=None)):
            result = await svc.get_positions_for_web()
        assert result["total"] == 2
        kinds = {r["kind"] for r in result["positions"]}
        assert kinds == {"position", "holding"}

    @pytest.mark.anyio
    async def test_resolves_security_id_per_row_when_adapter_lacks_one(self):
        # Fallback path only — the adapter's Position has no security_id
        # (e.g. a non-INDmoney adapter, or the rare row without one).
        import src.execution.service as svc
        adapter = MagicMock()
        adapter.get_positions = AsyncMock(return_value=[self._position()])
        adapter.get_holdings = AsyncMock(return_value=[])
        resolve_mock = AsyncMock(return_value="2885")
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(svc, "resolve_symbol", resolve_mock), \
             patch.object(svc._repo, "find_active_smart_order_for_symbol", AsyncMock(return_value=None)):
            result = await svc.get_positions_for_web()
        assert result["positions"][0]["security_id"] == "2885"
        resolve_mock.assert_awaited_once_with("RELIANCE", exchange="NSE", segment="DERIVATIVE")

    @pytest.mark.anyio
    async def test_uses_adapters_own_security_id_without_reresolving(self):
        # 2026-07-17 bug: re-resolving via resolve_symbol()'s symbol-text
        # search picked the WRONG contract for a real, currently-held NIFTY
        # weekly option (multiple expiries share one TRADING_SYMBOL string —
        # see resolve_security_id's own docstring), so the live-price
        # WebSocket subscribed to a different option entirely and its LTP
        # never matched. When the adapter's Position already carries the
        # real security_id, it must be used directly — resolve_symbol should
        # not be called at all.
        import src.execution.service as svc
        adapter = MagicMock()
        adapter.get_positions = AsyncMock(return_value=[self._position(security_id="57339")])
        adapter.get_holdings = AsyncMock(return_value=[])
        resolve_mock = AsyncMock(side_effect=AssertionError("should not re-resolve"))
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(svc, "resolve_symbol", resolve_mock), \
             patch.object(svc._repo, "find_active_smart_order_for_symbol", AsyncMock(return_value=None)):
            result = await svc.get_positions_for_web()
        assert result["positions"][0]["security_id"] == "57339"
        resolve_mock.assert_not_awaited()

    @pytest.mark.anyio
    async def test_holdings_resolved_as_equity_segment(self):
        import src.execution.service as svc
        adapter = MagicMock()
        adapter.get_positions = AsyncMock(return_value=[])
        adapter.get_holdings = AsyncMock(return_value=[self._holding()])
        resolve_mock = AsyncMock(return_value="11536")
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(svc, "resolve_symbol", resolve_mock), \
             patch.object(svc._repo, "find_active_smart_order_for_symbol", AsyncMock(return_value=None)):
            await svc.get_positions_for_web()
        resolve_mock.assert_awaited_once_with("TCS", exchange="NSE", segment="EQUITY")

    @pytest.mark.anyio
    async def test_resolve_failure_leaves_security_id_none_not_raise(self):
        import src.execution.service as svc
        adapter = MagicMock()
        adapter.get_positions = AsyncMock(return_value=[self._position()])
        adapter.get_holdings = AsyncMock(return_value=[])
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(svc, "resolve_symbol", AsyncMock(side_effect=RuntimeError("boom"))), \
             patch.object(svc._repo, "find_active_smart_order_for_symbol", AsyncMock(return_value=None)):
            result = await svc.get_positions_for_web()
        assert result["positions"][0]["security_id"] is None

    @pytest.mark.anyio
    async def test_attaches_active_sl_target(self):
        import src.execution.service as svc
        adapter = MagicMock()
        adapter.get_positions = AsyncMock(return_value=[self._position()])
        adapter.get_holdings = AsyncMock(return_value=[])
        active = {"broker_order_id": "GTT-1", "sl_trigger_price": 2820.0,
                  "tgt_trigger_price": 2950.0, "trailing_sl_points": 5.0}
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(svc, "resolve_symbol", AsyncMock(return_value="2885")), \
             patch.object(svc._repo, "find_active_smart_order_for_symbol", AsyncMock(return_value=active)):
            result = await svc.get_positions_for_web()
        assert result["positions"][0]["sl_target"] == {
            "broker_order_id": "GTT-1", "sl_trigger_price": 2820.0,
            "tgt_trigger_price": 2950.0, "trailing_sl_points": 5.0,
        }

    @pytest.mark.anyio
    async def test_no_active_sl_target_is_none(self):
        import src.execution.service as svc
        adapter = MagicMock()
        adapter.get_positions = AsyncMock(return_value=[self._position()])
        adapter.get_holdings = AsyncMock(return_value=[])
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(svc, "resolve_symbol", AsyncMock(return_value="2885")), \
             patch.object(svc._repo, "find_active_smart_order_for_symbol", AsyncMock(return_value=None)):
            result = await svc.get_positions_for_web()
        assert result["positions"][0]["sl_target"] is None

    @pytest.mark.anyio
    async def test_empty_when_no_positions_or_holdings(self):
        import src.execution.service as svc
        adapter = MagicMock()
        adapter.get_positions = AsyncMock(return_value=[])
        adapter.get_holdings = AsyncMock(return_value=[])
        with patch.object(svc, "get_broker_adapter", return_value=adapter):
            result = await svc.get_positions_for_web()
        assert result == {"positions": [], "total": 0}

    @pytest.mark.anyio
    async def test_zero_quantity_position_is_dropped(self):
        # A same-day position squared off to net_quantity=0 still comes back
        # from INDstocks as a row (2026-07-15 bug) — it isn't sellable/
        # modifiable and shouldn't clutter the positions page.
        import src.execution.service as svc
        adapter = MagicMock()
        adapter.get_positions = AsyncMock(return_value=[
            self._position(symbol="RELIANCE", quantity=0, avg=0.0, ltp=0.0, pnl=0.0),
            self._position(symbol="TCS", quantity=10),
        ])
        adapter.get_holdings = AsyncMock(return_value=[])
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(svc, "resolve_symbol", AsyncMock(return_value="11536")), \
             patch.object(svc._repo, "find_active_smart_order_for_symbol", AsyncMock(return_value=None)):
            result = await svc.get_positions_for_web()
        assert result["total"] == 1
        assert result["positions"][0]["symbol"] == "TCS"

    @pytest.mark.anyio
    async def test_zero_quantity_holding_is_dropped(self):
        import src.execution.service as svc
        adapter = MagicMock()
        adapter.get_positions = AsyncMock(return_value=[])
        adapter.get_holdings = AsyncMock(return_value=[
            self._holding(symbol="TCS", quantity=0, avg=0.0, ltp=0.0, pnl=0.0),
        ])
        with patch.object(svc, "get_broker_adapter", return_value=adapter):
            result = await svc.get_positions_for_web()
        assert result == {"positions": [], "total": 0}

    @pytest.mark.anyio
    async def test_negative_quantity_short_position_is_kept(self):
        # quantity is signed (negative = short) — only exactly zero should
        # be filtered, not falsy-but-nonzero short positions.
        import src.execution.service as svc
        adapter = MagicMock()
        adapter.get_positions = AsyncMock(return_value=[self._position(quantity=-10)])
        adapter.get_holdings = AsyncMock(return_value=[])
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(svc, "resolve_symbol", AsyncMock(return_value="2885")), \
             patch.object(svc._repo, "find_active_smart_order_for_symbol", AsyncMock(return_value=None)):
            result = await svc.get_positions_for_web()
        assert result["total"] == 1
        assert result["positions"][0]["quantity"] == -10


# ---------------------------------------------------------------------------
# ExecutionRepository — SL/target active-order lookup (2026-07-12)
# ---------------------------------------------------------------------------

class TestFindActiveSmartOrderForSymbol:

    @pytest.mark.anyio
    async def test_returns_none_when_sqlalchemy_unavailable(self):
        from src.execution.repository import ExecutionRepository
        repo = ExecutionRepository()
        with patch.dict("sys.modules", {"src.db.models": None}):
            assert await repo.find_active_smart_order_for_symbol("RELIANCE") is None

    @pytest.mark.anyio
    async def test_returns_none_when_db_unconfigured(self):
        from src.execution.repository import ExecutionRepository
        repo = ExecutionRepository()
        with patch("src.execution.repository.get_session", side_effect=RuntimeError("no DATABASE_URL")):
            assert await repo.find_active_smart_order_for_symbol("RELIANCE") is None

    @pytest.mark.anyio
    async def test_deactivate_sl_target_no_op_without_db(self):
        from src.execution.repository import ExecutionRepository
        repo = ExecutionRepository()
        with patch("src.execution.repository.get_session", side_effect=RuntimeError("no DATABASE_URL")):
            await repo.deactivate_sl_target("GTT-1")  # must not raise


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

    def _smart_req_with_trail(self):
        from src.brokers.models import OrderRequest
        return OrderRequest(
            security_id="2885", exchange="NSE", segment="EQUITY",
            transaction_type="BUY", quantity=1, symbol="RELIANCE",
            sl_trigger_price=2820.0, sl_limit_price=2810.0,
            trailing_sl_points=5.0,
        )

    @pytest.mark.anyio
    async def test_submit_order_starts_trailing_sl_when_requested(self):
        import src.execution.service as svc
        placed = {"status": "ok", "order_id": "GTT-1", "order_status": "CREATED", "body": {}}
        adapter = MagicMock()
        adapter.place_order = AsyncMock(return_value=placed)
        start_mock = MagicMock()
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(svc._repo, "save_order", AsyncMock(return_value=None)), \
             patch("src.execution.trailing_sl.start_trailing_sl", start_mock):
            await svc.submit_order(self._smart_req_with_trail(), source="telegram", user_id="u1")
        start_mock.assert_called_once()
        _, kwargs = start_mock.call_args
        assert kwargs["trail_points"] == 5.0
        assert kwargs["initial_sl_trigger"] == 2820.0

    @pytest.mark.anyio
    async def test_submit_order_does_not_start_trailing_sl_without_trail_points(self):
        import src.execution.service as svc
        placed = {"status": "ok", "order_id": "GTT-1", "body": {}}
        adapter = MagicMock()
        adapter.place_order = AsyncMock(return_value=placed)
        start_mock = MagicMock()
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(svc._repo, "save_order", AsyncMock(return_value=None)), \
             patch("src.execution.trailing_sl.start_trailing_sl", start_mock):
            await svc.submit_order(self._req(), source="telegram", user_id="u1")
        start_mock.assert_not_called()

    @pytest.mark.anyio
    async def test_repo_trailing_sl_methods_degrade_gracefully_without_db(self):
        # sqlalchemy/asyncpg are Linux-only per CLAUDE.md — on Windows dev
        # (this test's own environment) src.db.models raises ImportError, so
        # every new persistence method must no-op/return empty rather than
        # crash the trailing-SL loop that calls them.
        from src.execution.repository import ExecutionRepository
        repo = ExecutionRepository()
        await repo.upsert_trailing_sl_state(
            order_id="X1", exchange="NSE", security_id="1", side="BUY",
            broker="indmoney", trail_points=5.0, sl_trigger_price=100.0, sl_limit_price=99.0,
        )  # must not raise
        await repo.deactivate_trailing_sl_state("X1")  # must not raise
        assert await repo.list_active_trailing_sl_state() == []

    @pytest.mark.anyio
    async def test_submit_order_does_not_start_trailing_sl_on_rejected_order(self):
        import src.execution.service as svc
        placed = {"status": "error", "message": "rejected"}
        adapter = MagicMock()
        adapter.place_order = AsyncMock(return_value=placed)
        start_mock = MagicMock()
        with patch.object(svc, "get_broker_adapter", return_value=adapter), \
             patch.object(svc._repo, "save_order", AsyncMock(return_value=None)), \
             patch("src.execution.trailing_sl.start_trailing_sl", start_mock):
            await svc.submit_order(self._smart_req_with_trail(), source="telegram", user_id="u1")
        start_mock.assert_not_called()
