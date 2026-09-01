"""Regression tests for Audit-C2 — trailing SL must be cancelled on terminal
order status.

Finding: the order-status stream listener sent a Telegram alert on terminal
order states (FILLED/REJECTED/CANCELLED) but never called
trailing_sl.cancel_trailing_sl() or ExecutionRepository.deactivate_sl_target()
— a trailing-SL background task kept ratcheting a dead order indefinitely.

TC-1  terminal status (FILLED) cancels an active trailing SL for that order_id
TC-2  terminal status (REJECTED) cancels an active trailing SL for that order_id
TC-3  terminal status (CANCELLED) cancels an active trailing SL for that order_id
TC-4  non-terminal status (PARTIALLY_EXECUTED) does NOT cancel the trailing SL
TC-5  no-op (no crash, no cancel call) when no trailing SL is active for order_id
TC-6  deactivate_sl_target is awaited alongside cancel_trailing_sl
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

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


class TestTC1to3TerminalStatusCancelsTrailing:
    @pytest.mark.anyio
    @pytest.mark.parametrize("status", ["FILLED", "REJECTED", "CANCELLED"])
    async def test_terminal_status_cancels_active_trailer(self, status):
        from src.execution import order_update_listener as oul
        updates = [{"order_id": "X1", "order_status": status}]
        with patch.object(oul, "stream_order_updates", return_value=_fake_stream(updates)), \
             patch.object(oul, "_send_telegram", AsyncMock(return_value=True)), \
             patch.object(oul.ExecutionRepository, "find_by_broker_order_id", AsyncMock(return_value=None)), \
             patch.object(oul.trailing_sl, "is_trailing", return_value=True) as is_trailing_mock, \
             patch.object(oul.trailing_sl, "cancel_trailing_sl") as cancel_mock, \
             patch.object(oul.ExecutionRepository, "deactivate_sl_target", AsyncMock()) as deactivate_mock:
            await oul.run_order_update_listener("tok", "chat")
        is_trailing_mock.assert_called_once_with("X1")
        cancel_mock.assert_called_once_with("X1")
        deactivate_mock.assert_awaited_once_with("X1")


class TestTC4NonTerminalStatusLeavesTrailerRunning:
    @pytest.mark.anyio
    async def test_partially_executed_does_not_cancel(self):
        from src.execution import order_update_listener as oul
        updates = [{"order_id": "X1", "order_status": "PARTIALLY_EXECUTED"}]
        with patch.object(oul, "stream_order_updates", return_value=_fake_stream(updates)), \
             patch.object(oul, "_send_telegram", AsyncMock(return_value=True)), \
             patch.object(oul.ExecutionRepository, "find_by_broker_order_id", AsyncMock(return_value=None)), \
             patch.object(oul.trailing_sl, "is_trailing", return_value=True), \
             patch.object(oul.trailing_sl, "cancel_trailing_sl") as cancel_mock, \
             patch.object(oul.ExecutionRepository, "deactivate_sl_target", AsyncMock()) as deactivate_mock:
            await oul.run_order_update_listener("tok", "chat")
        cancel_mock.assert_not_called()
        deactivate_mock.assert_not_awaited()


class TestTC5NoActiveTrailerIsSafeNoOp:
    @pytest.mark.anyio
    async def test_filled_with_no_trailer_does_not_call_cancel(self):
        from src.execution import order_update_listener as oul
        updates = [{"order_id": "X1", "order_status": "FILLED"}]
        with patch.object(oul, "stream_order_updates", return_value=_fake_stream(updates)), \
             patch.object(oul, "_send_telegram", AsyncMock(return_value=True)), \
             patch.object(oul.ExecutionRepository, "find_by_broker_order_id", AsyncMock(return_value=None)), \
             patch.object(oul.trailing_sl, "is_trailing", return_value=False), \
             patch.object(oul.trailing_sl, "cancel_trailing_sl") as cancel_mock, \
             patch.object(oul.ExecutionRepository, "deactivate_sl_target", AsyncMock()) as deactivate_mock:
            await oul.run_order_update_listener("tok", "chat")
        cancel_mock.assert_not_called()
        deactivate_mock.assert_not_awaited()

    @pytest.mark.anyio
    async def test_still_sends_alert_even_when_no_trailer(self):
        from src.execution import order_update_listener as oul
        updates = [{"order_id": "X1", "order_status": "FILLED"}]
        send_mock = AsyncMock(return_value=True)
        with patch.object(oul, "stream_order_updates", return_value=_fake_stream(updates)), \
             patch.object(oul, "_send_telegram", send_mock), \
             patch.object(oul.ExecutionRepository, "find_by_broker_order_id", AsyncMock(return_value=None)), \
             patch.object(oul.trailing_sl, "is_trailing", return_value=False):
            await oul.run_order_update_listener("tok", "chat")
        send_mock.assert_awaited_once()
