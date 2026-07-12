"""Phase 23 — mobile order web app route tests.

Drives the ASGI _app() directly (same pattern as test_oauth_flow.py). The
/trade routes are gated solely by TRADE_PIN and never touch the OAuth flow.
"""
from __future__ import annotations

import json
import os

import pytest
from unittest.mock import AsyncMock, patch

from src.server import _app, _is_market_session_open_safe


async def _call(path, method="GET", body=b"", headers=None, query_string=b""):
    scope = {
        "type": "http", "method": method, "path": path,
        "query_string": query_string, "headers": headers or [(b"host", b"testserver")],
        "scheme": "http",
    }
    chunks = [body]

    async def receive():
        return {"type": "http.request", "body": chunks.pop(0) if chunks else b"", "more_body": False}

    responses = []

    async def send(message):
        responses.append(message)

    await _app(scope, receive, send)
    status, resp_body = None, b""
    for r in responses:
        if r["type"] == "http.response.start":
            status = r["status"]
        elif r["type"] == "http.response.body":
            resp_body += r.get("body", b"")
    return status, resp_body


def _json_body(**kw):
    return json.dumps(kw).encode()


@pytest.mark.anyio
async def test_trade_page_served():
    status, body = await _call("/trade")
    assert status == 200
    assert b"Place Order" in body


@pytest.mark.anyio
async def test_preview_rejects_bad_pin():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}):
        status, body = await _call(
            "/trade/preview", method="POST",
            body=_json_body(pin="0000", symbol="RELIANCE", side="BUY", quantity=1),
        )
    assert status == 403
    assert json.loads(body)["error"] == "invalid PIN"


@pytest.mark.anyio
async def test_preview_disabled_when_pin_unset():
    # No TRADE_PIN configured → feature disabled, even a blank PIN is rejected.
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TRADE_PIN", None)
        status, _ = await _call(
            "/trade/preview", method="POST",
            body=_json_body(pin="", symbol="RELIANCE", side="BUY", quantity=1),
        )
    assert status == 403


@pytest.mark.anyio
async def test_preview_valid_returns_summary():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.market.calendar.is_market_session_open", return_value=True):
        status, body = await _call(
            "/trade/preview", method="POST",
            body=_json_body(pin="1234", symbol="RELIANCE", side="BUY",
                            quantity=2, order_type="LIMIT", limit_price=2870, product="CNC"),
        )
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert "RELIANCE" in data["summary_html"]
    assert "LIMIT" in data["summary_html"]
    assert "AMO" not in data["summary_html"]


@pytest.mark.anyio
async def test_preview_shows_amo_note_when_market_closed():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.market.calendar.is_market_session_open", return_value=False):
        status, body = await _call(
            "/trade/preview", method="POST",
            body=_json_body(pin="1234", symbol="RELIANCE", side="BUY",
                            quantity=2, order_type="LIMIT", limit_price=2870, product="CNC"),
        )
    assert status == 200
    data = json.loads(body)
    assert "AMO" in data["summary_html"]
    assert "Market is closed" in data["summary_html"]


@pytest.mark.anyio
async def test_preview_invalid_fields():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}):
        status, body = await _call(
            "/trade/preview", method="POST",
            body=_json_body(pin="1234", symbol="", side="BUY", quantity=1),
        )
    assert status == 400
    assert "error" in json.loads(body)


@pytest.mark.anyio
async def test_is_market_session_open_safe_defaults_closed_on_error():
    # A calendar-provider fetch failure must not silently read as "market
    # open" — that reproduces the exact 512 Internal Server Error bug from
    # INDstocks this check exists to prevent (confirmed 2026-07-12).
    with patch("src.market.calendar.is_market_session_open", side_effect=RuntimeError("boom")):
        result = await _is_market_session_open_safe()
    assert result is False


@pytest.mark.anyio
async def test_place_rejects_bad_pin_before_touching_broker():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.execution.service.submit_order", AsyncMock()) as sub:
        status, _ = await _call(
            "/trade/place", method="POST",
            body=_json_body(pin="wrong", symbol="RELIANCE", side="BUY", quantity=1),
        )
    assert status == 403
    sub.assert_not_awaited()  # PIN gate short-circuits before any order


@pytest.mark.anyio
async def test_place_valid_pin_places_order():
    placed = {"status": "ok", "order_id": "DRV-9", "order_status": "O-PENDING"}
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.market.calendar.is_market_session_open", return_value=True), \
         patch("src.execution.service.resolve_symbol", AsyncMock(return_value="2885")), \
         patch("src.execution.service.submit_order", AsyncMock(return_value=placed)) as sub:
        status, body = await _call(
            "/trade/place", method="POST",
            body=_json_body(pin="1234", symbol="RELIANCE", side="BUY", quantity=1),
        )
    assert status == 200
    assert json.loads(body)["order_id"] == "DRV-9"
    sub.assert_awaited_once()
    assert sub.call_args.kwargs["source"] == "web"
    assert sub.call_args.args[0].is_amo is False


@pytest.mark.anyio
async def test_place_auto_amo_when_market_closed():
    # Confirmed against INDstocks' docs (2026-07-12): AMO orders require
    # is_amo=true + DAY validity and queue as O-PENDING until next session's
    # open. Placing a regular-session order while the market is closed
    # previously surfaced as an opaque 512 Internal Server Error from
    # INDstocks — this auto-flags it as AMO instead.
    placed = {"status": "ok", "order_id": "DRV-10", "order_status": "O-PENDING"}
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.market.calendar.is_market_session_open", return_value=False), \
         patch("src.execution.service.resolve_symbol", AsyncMock(return_value="2885")), \
         patch("src.execution.service.submit_order", AsyncMock(return_value=placed)) as sub:
        status, body = await _call(
            "/trade/place", method="POST",
            body=_json_body(pin="1234", symbol="RELIANCE", side="BUY", quantity=1),
        )
    assert status == 200
    sub.assert_awaited_once()
    placed_req = sub.call_args.args[0]
    assert placed_req.is_amo is True
    assert placed_req.validity == "DAY"


@pytest.mark.anyio
async def test_place_smart_order_rejected_when_market_closed():
    # AMO support for INDstocks' /smart/order (SL/target leg) endpoint isn't
    # confirmed — only the plain /order endpoint's is_amo behavior is. The
    # web form can't set SL/target fields today, so this exercises the
    # defensive guard directly via a patched _build_order_from_web.
    from src.brokers.models import OrderRequest
    smart_req = OrderRequest(
        security_id="2885", exchange="NSE", segment="EQUITY",
        transaction_type="BUY", quantity=1, sl_trigger_price=100.0,
    )
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.market.calendar.is_market_session_open", return_value=False), \
         patch("src.server._build_order_from_web", return_value=(smart_req, None)), \
         patch("src.execution.service.submit_order", AsyncMock()) as sub:
        status, body = await _call(
            "/trade/place", method="POST",
            body=_json_body(pin="1234", symbol="RELIANCE", side="BUY", quantity=1),
        )
    assert status == 400
    assert "closed" in json.loads(body)["error"].lower()
    sub.assert_not_awaited()


@pytest.mark.anyio
async def test_place_unknown_symbol_returns_400():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.market.calendar.is_market_session_open", return_value=True), \
         patch("src.execution.service.resolve_symbol", AsyncMock(return_value=None)), \
         patch("src.execution.service.submit_order", AsyncMock()) as sub:
        status, body = await _call(
            "/trade/place", method="POST",
            body=_json_body(pin="1234", symbol="MADEUP", side="BUY", quantity=1),
        )
    assert status == 400
    assert "not found" in json.loads(body)["error"]
    sub.assert_not_awaited()


@pytest.mark.anyio
async def test_place_with_client_security_id_skips_ambiguous_resolve():
    # When the user picked an exact contract from the /trade/symbols dropdown,
    # the client sends that security_id — the server must trust it and skip
    # resolve_symbol entirely, since resolving by symbol text is ambiguous for
    # weekly index options sharing a display name (see search_instruments'
    # docstring in src/brokers/indmoney.py).
    placed = {"status": "ok", "order_id": "DRV-42", "order_status": "O-PENDING"}
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.market.calendar.is_market_session_open", return_value=True), \
         patch("src.execution.service.resolve_symbol", AsyncMock()) as resolve, \
         patch("src.execution.service.submit_order", AsyncMock(return_value=placed)) as sub:
        status, body = await _call(
            "/trade/place", method="POST",
            body=_json_body(pin="1234", symbol="NIFTY-JUL2026-27500-PE",
                            security_id="222", side="BUY", quantity=75),
        )
    assert status == 200
    resolve.assert_not_awaited()  # exact id trusted, no ambiguous re-resolve
    sub.assert_awaited_once()
    placed_req = sub.call_args.args[0]
    assert placed_req.security_id == "222"
    # Confirmed bug (2026-07-12): with no explicit segment in the request,
    # this falls back to _is_derivative_symbol(symbol) — which must
    # recognize INDstocks' hyphenated TRADING_SYMBOL format, or every option
    # order gets silently misclassified as segment="EQUITY".
    assert placed_req.segment == "DERIVATIVE"


@pytest.mark.anyio
async def test_place_trusts_client_sent_segment_from_dropdown():
    # Confirmed bug (2026-07-12): the web dropdown already knows the correct
    # segment (search_symbols tags each result by which instrument-master
    # source it came from), but the client never sent it and the server
    # re-derived it from a regex that doesn't match INDstocks' hyphenated
    # option symbols — misclassifying every option order as segment="EQUITY"
    # and getting rejected by INDstocks with a 512 Internal Server Error.
    # The client-sent segment must now be trusted, same as security_id.
    placed = {"status": "ok", "order_id": "DRV-43", "order_status": "O-PENDING"}
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.market.calendar.is_market_session_open", return_value=True), \
         patch("src.execution.service.resolve_symbol", AsyncMock()) as resolve, \
         patch("src.execution.service.submit_order", AsyncMock(return_value=placed)) as sub:
        status, body = await _call(
            "/trade/place", method="POST",
            body=_json_body(pin="1234", symbol="NIFTY-JUL2026-27500-PE",
                            security_id="222", segment="DERIVATIVE", side="BUY", quantity=75),
        )
    assert status == 200
    resolve.assert_not_awaited()
    sub.assert_awaited_once()
    placed_req = sub.call_args.args[0]
    assert placed_req.segment == "DERIVATIVE"


# ---------------------------------------------------------------------------
# /trade/symbols — autocomplete search
# ---------------------------------------------------------------------------

def _qs(**kw):
    return "&".join(f"{k}={v}" for k, v in kw.items()).encode()


@pytest.mark.anyio
async def test_symbols_rejects_bad_pin():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.execution.service.search_symbols", AsyncMock()) as search:
        status, body = await _call("/trade/symbols", query_string=_qs(q="reliance", pin="0000"))
    assert status == 403
    search.assert_not_awaited()


@pytest.mark.anyio
async def test_symbols_short_query_returns_empty_without_calling_service():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.execution.service.search_symbols", AsyncMock()) as search:
        status, body = await _call("/trade/symbols", query_string=_qs(q="r", pin="1234"))
    assert status == 200
    assert json.loads(body)["results"] == []
    search.assert_not_awaited()


@pytest.mark.anyio
async def test_symbols_valid_query_returns_results():
    results = [{"symbol": "RELIANCE", "name": "Reliance Industries", "exchange": "NSE", "segment": "EQUITY"}]
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.execution.service.search_symbols", AsyncMock(return_value=results)) as search:
        status, body = await _call("/trade/symbols", query_string=_qs(q="reliance", pin="1234"))
    assert status == 200
    data = json.loads(body)
    assert data["results"] == results
    search.assert_awaited_once()
    assert search.call_args.args[0] == "reliance"


@pytest.mark.anyio
async def test_symbols_disabled_when_pin_unset():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TRADE_PIN", None)
        status, _ = await _call("/trade/symbols", query_string=_qs(q="reliance", pin=""))
    assert status == 403


# ---------------------------------------------------------------------------
# SL/target/trailing-SL on the web form (2026-07-12)
# ---------------------------------------------------------------------------

class TestBuildOrderFromWebSlTarget:

    def test_no_legs_by_default(self):
        from src.server import _build_order_from_web
        req, err = _build_order_from_web({"symbol": "RELIANCE", "side": "BUY", "quantity": 1})
        assert err is None
        assert req.sl_trigger_price is None
        assert not req.is_smart_order

    def test_sl_trigger_sets_smart_order(self):
        from src.server import _build_order_from_web
        req, err = _build_order_from_web({
            "symbol": "RELIANCE", "side": "BUY", "quantity": 1, "sl_trigger_price": 2820,
        })
        assert err is None
        assert req.sl_trigger_price == 2820.0
        assert req.sl_limit_price == 2820.0  # defaults to trigger
        assert req.is_smart_order

    def test_sl_limit_overrides_default(self):
        from src.server import _build_order_from_web
        req, err = _build_order_from_web({
            "symbol": "RELIANCE", "side": "BUY", "quantity": 1,
            "sl_trigger_price": 2820, "sl_limit_price": 2810,
        })
        assert err is None
        assert req.sl_limit_price == 2810.0

    def test_target_leg(self):
        from src.server import _build_order_from_web
        req, err = _build_order_from_web({
            "symbol": "RELIANCE", "side": "BUY", "quantity": 1, "tgt_trigger_price": 2950,
        })
        assert err is None
        assert req.tgt_trigger_price == 2950.0
        assert req.tgt_limit_price == 2950.0

    def test_trail_without_sl_is_error(self):
        from src.server import _build_order_from_web
        req, err = _build_order_from_web({
            "symbol": "RELIANCE", "side": "BUY", "quantity": 1, "trailing_sl_points": 5,
        })
        assert req is None
        assert "trail" in err.lower()

    def test_trail_with_sl_ok(self):
        from src.server import _build_order_from_web
        req, err = _build_order_from_web({
            "symbol": "RELIANCE", "side": "BUY", "quantity": 1,
            "sl_trigger_price": 2820, "trailing_sl_points": 5,
        })
        assert err is None
        assert req.trailing_sl_points == 5.0

    def test_zero_or_negative_leg_ignored(self):
        from src.server import _build_order_from_web
        req, err = _build_order_from_web({
            "symbol": "RELIANCE", "side": "BUY", "quantity": 1, "sl_trigger_price": -5,
        })
        assert err is None
        assert req.sl_trigger_price is None
        assert not req.is_smart_order

    def test_junk_leg_value_ignored_not_an_error(self):
        from src.server import _build_order_from_web
        req, err = _build_order_from_web({
            "symbol": "RELIANCE", "side": "BUY", "quantity": 1, "sl_trigger_price": "abc",
        })
        assert err is None
        assert req.sl_trigger_price is None


@pytest.mark.anyio
async def test_preview_shows_sl_target_trail_lines():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.market.calendar.is_market_session_open", return_value=True):
        status, body = await _call(
            "/trade/preview", method="POST",
            body=_json_body(pin="1234", symbol="RELIANCE", side="BUY", quantity=1,
                            sl_trigger_price=2820, tgt_trigger_price=2950, trailing_sl_points=5),
        )
    assert status == 200
    html = json.loads(body)["summary_html"]
    assert "SL" in html and "2820" in html
    assert "Target" in html and "2950" in html
    assert "Trailing SL" in html and "5" in html


@pytest.mark.anyio
async def test_place_smart_order_wires_sl_target_through_to_order_request():
    placed = {"status": "ok", "order_id": "GTT-1", "order_status": "CREATED"}
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.market.calendar.is_market_session_open", return_value=True), \
         patch("src.execution.service.submit_order", AsyncMock(return_value=placed)) as sub:
        status, body = await _call(
            "/trade/place", method="POST",
            body=_json_body(pin="1234", symbol="RELIANCE", security_id="2885", side="BUY", quantity=1,
                            sl_trigger_price=2820, tgt_trigger_price=2950),
        )
    assert status == 200
    sub.assert_awaited_once()
    req = sub.call_args.args[0]
    assert req.sl_trigger_price == 2820.0
    assert req.tgt_trigger_price == 2950.0


# ---------------------------------------------------------------------------
# /positions page + /positions/data
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_positions_page_served():
    status, body = await _call("/positions")
    assert status == 200
    assert b"Positions" in body


@pytest.mark.anyio
async def test_positions_data_rejects_bad_pin():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.execution.service.get_positions_for_web", AsyncMock()) as fn:
        status, body = await _call("/positions/data", query_string=_qs(pin="0000"))
    assert status == 403
    fn.assert_not_awaited()


@pytest.mark.anyio
async def test_positions_data_returns_service_result():
    result = {"positions": [{"symbol": "RELIANCE", "pnl": 120.0}], "total": 1}
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.execution.service.get_positions_for_web", AsyncMock(return_value=result)):
        status, body = await _call("/positions/data", query_string=_qs(pin="1234"))
    assert status == 200
    assert json.loads(body) == result


@pytest.mark.anyio
async def test_positions_data_502_on_fetch_failure():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.execution.service.get_positions_for_web", AsyncMock(side_effect=RuntimeError("boom"))):
        status, body = await _call("/positions/data", query_string=_qs(pin="1234"))
    assert status == 502


# ---------------------------------------------------------------------------
# /trade/sell — one-tap sell from the positions page
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_sell_rejects_bad_pin():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.execution.service.submit_order", AsyncMock()) as sub:
        status, _ = await _call(
            "/trade/sell", method="POST",
            body=_json_body(pin="0000", symbol="RELIANCE", security_id="2885",
                            exchange="NSE", segment="EQUITY", quantity=1),
        )
    assert status == 403
    sub.assert_not_awaited()


@pytest.mark.anyio
async def test_sell_forces_side_sell_regardless_of_input():
    placed = {"status": "ok", "order_id": "X1"}
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.market.calendar.is_market_session_open", return_value=True), \
         patch("src.execution.service.submit_order", AsyncMock(return_value=placed)) as sub:
        status, body = await _call(
            "/trade/sell", method="POST",
            body=_json_body(pin="1234", symbol="RELIANCE", security_id="2885",
                            exchange="NSE", segment="EQUITY", quantity=1, side="BUY"),
        )
    assert status == 200
    req = sub.call_args.args[0]
    assert req.transaction_type == "SELL"


@pytest.mark.anyio
async def test_sell_defaults_to_market_order():
    placed = {"status": "ok", "order_id": "X1"}
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.market.calendar.is_market_session_open", return_value=True), \
         patch("src.execution.service.submit_order", AsyncMock(return_value=placed)) as sub:
        status, body = await _call(
            "/trade/sell", method="POST",
            body=_json_body(pin="1234", symbol="RELIANCE", security_id="2885",
                            exchange="NSE", segment="EQUITY", quantity=1),
        )
    assert status == 200
    req = sub.call_args.args[0]
    assert req.order_type == "MARKET"


@pytest.mark.anyio
async def test_sell_auto_amo_when_market_closed():
    placed = {"status": "ok", "order_id": "X1"}
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.market.calendar.is_market_session_open", return_value=False), \
         patch("src.execution.service.submit_order", AsyncMock(return_value=placed)) as sub:
        status, body = await _call(
            "/trade/sell", method="POST",
            body=_json_body(pin="1234", symbol="RELIANCE", security_id="2885",
                            exchange="NSE", segment="EQUITY", quantity=1),
        )
    assert status == 200
    req = sub.call_args.args[0]
    assert req.is_amo is True


@pytest.mark.anyio
async def test_sell_resolves_security_id_when_missing():
    placed = {"status": "ok", "order_id": "X1"}
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.market.calendar.is_market_session_open", return_value=True), \
         patch("src.execution.service.resolve_symbol", AsyncMock(return_value="9999")), \
         patch("src.execution.service.submit_order", AsyncMock(return_value=placed)) as sub:
        status, body = await _call(
            "/trade/sell", method="POST",
            body=_json_body(pin="1234", symbol="RELIANCE", exchange="NSE", segment="EQUITY", quantity=1),
        )
    assert status == 200
    req = sub.call_args.args[0]
    assert req.security_id == "9999"


# ---------------------------------------------------------------------------
# /trade/modify — SL/target modify on an existing smart order
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_modify_rejects_bad_pin():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.brokers.indmoney.INDmoneyBroker.modify_smart_order", AsyncMock()) as mod:
        status, _ = await _call(
            "/trade/modify", method="POST",
            body=_json_body(pin="0000", order_id="GTT-1", sl_trigger_price=2830),
        )
    assert status == 403
    mod.assert_not_awaited()


@pytest.mark.anyio
async def test_modify_requires_order_id():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}):
        status, body = await _call(
            "/trade/modify", method="POST",
            body=_json_body(pin="1234", sl_trigger_price=2830),
        )
    assert status == 400
    assert "order_id" in json.loads(body)["error"]


@pytest.mark.anyio
async def test_modify_requires_at_least_one_leg():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}):
        status, body = await _call(
            "/trade/modify", method="POST",
            body=_json_body(pin="1234", order_id="GTT-1"),
        )
    assert status == 400


@pytest.mark.anyio
async def test_modify_calls_broker_with_sl_leg():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.brokers.indmoney.INDmoneyBroker.modify_smart_order",
               AsyncMock(return_value={"status": "ok"})) as mod:
        status, body = await _call(
            "/trade/modify", method="POST",
            body=_json_body(pin="1234", order_id="GTT-1", sl_trigger_price=2830, sl_limit_price=2825),
        )
    assert status == 200
    mod.assert_awaited_once_with("GTT-1", sl_trigger_price=2830.0, sl_limit_price=2825.0)


@pytest.mark.anyio
async def test_modify_sl_limit_defaults_to_trigger():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.brokers.indmoney.INDmoneyBroker.modify_smart_order",
               AsyncMock(return_value={"status": "ok"})) as mod:
        status, body = await _call(
            "/trade/modify", method="POST",
            body=_json_body(pin="1234", order_id="GTT-1", sl_trigger_price=2830),
        )
    assert status == 200
    mod.assert_awaited_once_with("GTT-1", sl_trigger_price=2830.0, sl_limit_price=2830.0)


@pytest.mark.anyio
async def test_modify_502_on_broker_error():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.brokers.indmoney.INDmoneyBroker.modify_smart_order",
               AsyncMock(return_value={"status": "error", "message": "invalid"})):
        status, body = await _call(
            "/trade/modify", method="POST",
            body=_json_body(pin="1234", order_id="GTT-1", sl_trigger_price=2830),
        )
    assert status == 502


# ---------------------------------------------------------------------------
# /positions/summary
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_summary_rejects_bad_pin():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.execution.service.get_positions_for_web", AsyncMock()) as fn:
        status, _ = await _call("/positions/summary", query_string=_qs(pin="0000"))
    assert status == 403
    fn.assert_not_awaited()


@pytest.mark.anyio
async def test_summary_aggregates_positions():
    result = {"positions": [
        {"symbol": "A", "pnl": 100.0, "sl_target": {"broker_order_id": "X"}},
        {"symbol": "B", "pnl": -40.0, "sl_target": None},
    ], "total": 2}
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.execution.service.get_positions_for_web", AsyncMock(return_value=result)):
        status, body = await _call("/positions/summary", query_string=_qs(pin="1234"))
    assert status == 200
    data = json.loads(body)
    assert data["total_positions"] == 2
    assert data["total_pnl"] == 60.0
    assert data["with_sl_or_target"] == 1
