"""Tests for src/execution/order_update_listener.py — live order-fill/rejection
Telegram alerts driven by the real INDstocks WS order-updates feed."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def _fake_stream(updates):
    for u in updates:
        yield u


@pytest.fixture(autouse=True)
def _clear_dedup_state():
    from src.execution import order_update_listener as oul
    oul._last_alerted_status.clear()
    yield
    oul._last_alerted_status.clear()


class TestFormatAlert:

    def test_includes_symbol_side_qty_from_logged_order(self):
        from src.execution.order_update_listener import _format_alert
        logged = {"transaction_type": "BUY", "symbol": "RELIANCE", "quantity": 1}
        update = {"filled_quantity": 1, "remaining_quantity": 0, "average_price": 2870.5}
        msg = _format_alert("X1", "FILLED", logged, update)
        assert "BUY RELIANCE x1" in msg
        assert "X1" in msg
        assert "FILLED" in msg
        assert "2870.5" in msg

    def test_falls_back_when_order_not_found_in_log(self):
        from src.execution.order_update_listener import _format_alert
        msg = _format_alert("X1", "REJECTED", None, {})
        assert "Order" in msg
        assert "REJECTED" in msg

    def test_omits_fill_fields_when_absent(self):
        from src.execution.order_update_listener import _format_alert
        msg = _format_alert("X1", "CREATED", {"transaction_type": "BUY", "symbol": "TCS", "quantity": 5}, {})
        assert "Filled" not in msg
        assert "Avg price" not in msg


class TestRunOrderUpdateListener:

    @pytest.mark.anyio
    async def test_no_token_or_chat_id_exits_without_streaming(self):
        from src.execution import order_update_listener as oul
        with patch.object(oul, "stream_order_updates") as stream_mock:
            await oul.run_order_update_listener("", "")
            await oul.run_order_update_listener("tok", "")
            await oul.run_order_update_listener("", "chat")
        stream_mock.assert_not_called()

    @pytest.mark.anyio
    async def test_sends_alert_for_fill(self):
        from src.execution import order_update_listener as oul
        updates = [{"order_id": "X1", "order_status": "FILLED", "filled_quantity": 1}]
        send_mock = AsyncMock(return_value=True)
        with patch.object(oul, "stream_order_updates", return_value=_fake_stream(updates)), \
             patch.object(oul, "_send_telegram", send_mock), \
             patch.object(oul.ExecutionRepository, "find_by_broker_order_id", AsyncMock(return_value=None)):
            await oul.run_order_update_listener("tok", "chat")
        send_mock.assert_awaited_once()
        args = send_mock.call_args.args
        assert args[0] == "tok"
        assert args[1] == "chat"
        assert "X1" in args[2]

    @pytest.mark.anyio
    async def test_looks_up_logged_order_for_context(self):
        from src.execution import order_update_listener as oul
        updates = [{"order_id": "X1", "order_status": "FILLED"}]
        lookup_mock = AsyncMock(return_value={"transaction_type": "SELL", "symbol": "TCS", "quantity": 5})
        with patch.object(oul, "stream_order_updates", return_value=_fake_stream(updates)), \
             patch.object(oul, "_send_telegram", AsyncMock(return_value=True)) as send_mock, \
             patch.object(oul.ExecutionRepository, "find_by_broker_order_id", lookup_mock):
            await oul.run_order_update_listener("tok", "chat")
        lookup_mock.assert_awaited_once_with("X1")
        assert "SELL TCS x5" in send_mock.call_args.args[2]

    @pytest.mark.anyio
    async def test_deduplicates_repeated_status_for_same_order(self):
        from src.execution import order_update_listener as oul
        updates = [
            {"order_id": "X1", "order_status": "FILLED"},
            {"order_id": "X1", "order_status": "FILLED"},  # duplicate push
        ]
        send_mock = AsyncMock(return_value=True)
        with patch.object(oul, "stream_order_updates", return_value=_fake_stream(updates)), \
             patch.object(oul, "_send_telegram", send_mock), \
             patch.object(oul.ExecutionRepository, "find_by_broker_order_id", AsyncMock(return_value=None)):
            await oul.run_order_update_listener("tok", "chat")
        send_mock.assert_awaited_once()

    @pytest.mark.anyio
    async def test_alerts_again_when_status_changes(self):
        from src.execution import order_update_listener as oul
        updates = [
            {"order_id": "X1", "order_status": "PARTIALLY_EXECUTED"},
            {"order_id": "X1", "order_status": "FILLED"},
        ]
        send_mock = AsyncMock(return_value=True)
        with patch.object(oul, "stream_order_updates", return_value=_fake_stream(updates)), \
             patch.object(oul, "_send_telegram", send_mock), \
             patch.object(oul.ExecutionRepository, "find_by_broker_order_id", AsyncMock(return_value=None)):
            await oul.run_order_update_listener("tok", "chat")
        assert send_mock.await_count == 2

    @pytest.mark.anyio
    async def test_missing_order_id_or_status_skipped(self):
        from src.execution import order_update_listener as oul
        updates = [{"order_status": "FILLED"}, {"order_id": "X1"}, {}]
        send_mock = AsyncMock(return_value=True)
        with patch.object(oul, "stream_order_updates", return_value=_fake_stream(updates)), \
             patch.object(oul, "_send_telegram", send_mock):
            await oul.run_order_update_listener("tok", "chat")
        send_mock.assert_not_awaited()

    @pytest.mark.anyio
    async def test_does_not_mark_dedup_state_if_send_fails(self):
        from src.execution import order_update_listener as oul
        updates = [
            {"order_id": "X1", "order_status": "FILLED"},
            {"order_id": "X1", "order_status": "FILLED"},
        ]
        send_mock = AsyncMock(return_value=False)  # send fails both times
        with patch.object(oul, "stream_order_updates", return_value=_fake_stream(updates)), \
             patch.object(oul, "_send_telegram", send_mock), \
             patch.object(oul.ExecutionRepository, "find_by_broker_order_id", AsyncMock(return_value=None)):
            await oul.run_order_update_listener("tok", "chat")
        assert send_mock.await_count == 2  # retried since dedup state never got set

    @pytest.mark.anyio
    async def test_malformed_update_does_not_kill_the_listener(self):
        from src.execution import order_update_listener as oul

        async def _bad_stream():
            yield {"order_id": "X1", "order_status": "FILLED"}
            raise ValueError("boom mid-stream")

        with patch.object(oul, "stream_order_updates", return_value=_bad_stream()), \
             patch.object(oul, "_send_telegram", AsyncMock(return_value=True)), \
             patch.object(oul.ExecutionRepository, "find_by_broker_order_id", AsyncMock(return_value=None)):
            with pytest.raises(ValueError):
                # the generator itself raising propagates (stream_order_updates
                # owns reconnect/backoff) — this test documents that the
                # listener's per-message try/except does NOT swallow a
                # generator-level failure, only per-message handling errors.
                await oul.run_order_update_listener("tok", "chat")


class TestFindByBrokerOrderId:

    @pytest.mark.anyio
    async def test_returns_none_when_sqlalchemy_unavailable(self):
        from src.execution.repository import ExecutionRepository
        repo = ExecutionRepository()
        with patch.dict("sys.modules", {"src.db.models": None}):
            result = await repo.find_by_broker_order_id("X1")
        assert result is None

    @pytest.mark.anyio
    async def test_returns_none_when_db_unconfigured(self):
        from src.execution.repository import ExecutionRepository
        repo = ExecutionRepository()
        with patch("src.execution.repository.get_session", side_effect=RuntimeError("no DATABASE_URL")):
            result = await repo.find_by_broker_order_id("X1")
        assert result is None
