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
