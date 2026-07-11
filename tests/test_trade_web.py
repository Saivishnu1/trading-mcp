"""Phase 23 — mobile order web app route tests.

Drives the ASGI _app() directly (same pattern as test_oauth_flow.py). The
/trade routes are gated solely by TRADE_PIN and never touch the OAuth flow.
"""
from __future__ import annotations

import json
import os

import pytest
from unittest.mock import AsyncMock, patch

from src.server import _app


async def _call(path, method="GET", body=b"", headers=None):
    scope = {
        "type": "http", "method": method, "path": path,
        "query_string": b"", "headers": headers or [(b"host", b"testserver")],
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
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}):
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


@pytest.mark.anyio
async def test_place_unknown_symbol_returns_400():
    with patch.dict(os.environ, {"TRADE_PIN": "1234"}), \
         patch("src.execution.service.resolve_symbol", AsyncMock(return_value=None)), \
         patch("src.execution.service.submit_order", AsyncMock()) as sub:
        status, body = await _call(
            "/trade/place", method="POST",
            body=_json_body(pin="1234", symbol="MADEUP", side="BUY", quantity=1),
        )
    assert status == 400
    assert "not found" in json.loads(body)["error"]
    sub.assert_not_awaited()
