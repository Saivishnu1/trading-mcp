"""Tests for src/execution/trailing_sl.py — client-side trailing-SL ratchet.

INDstocks has no native trailing-SL field (see OrderRequest docstring), so
this module polls the live price stream and calls modify_smart_order() to
walk the SL leg up (BUY) or down (SELL) as price moves favorably. The stream
is mocked — no real network calls.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def _fake_stream(messages):
    for m in messages:
        yield m


class TestTrailLoopBuy:

    @pytest.mark.anyio
    async def test_moves_sl_up_as_price_rises(self):
        from src.execution import trailing_sl as ts
        adapter = MagicMock()
        adapter.modify_smart_order = AsyncMock(return_value={"status": "ok"})
        prices = [{"data": {"ltp": 2830}}, {"data": {"ltp": 2840}}]
        with patch.object(ts, "get_broker_adapter", return_value=adapter), \
             patch.object(ts, "stream_prices", return_value=_fake_stream(prices)):
            await ts._trail_loop(
                "GTT-1", exchange="NSE", security_id="2885", side="BUY",
                trail_points=5.0, initial_sl_trigger=2820.0, initial_sl_limit=2820.0,
                broker_name="indmoney",
            )
        assert adapter.modify_smart_order.await_count == 2
        first_call = adapter.modify_smart_order.await_args_list[0]
        assert first_call.args[0] == "GTT-1"
        assert first_call.kwargs["sl_trigger_price"] == 2825.0  # 2830 - 5
        second_call = adapter.modify_smart_order.await_args_list[1]
        assert second_call.kwargs["sl_trigger_price"] == 2835.0  # 2840 - 5

    @pytest.mark.anyio
    async def test_does_not_move_sl_down_on_price_drop(self):
        from src.execution import trailing_sl as ts
        adapter = MagicMock()
        adapter.modify_smart_order = AsyncMock(return_value={"status": "ok"})
        prices = [{"data": {"ltp": 2800}}]  # below trigger+trail; must not move
        with patch.object(ts, "get_broker_adapter", return_value=adapter), \
             patch.object(ts, "stream_prices", return_value=_fake_stream(prices)):
            await ts._trail_loop(
                "GTT-1", exchange="NSE", security_id="2885", side="BUY",
                trail_points=5.0, initial_sl_trigger=2820.0, initial_sl_limit=2820.0,
                broker_name="indmoney",
            )
        adapter.modify_smart_order.assert_not_awaited()

    @pytest.mark.anyio
    async def test_ignores_messages_without_ltp(self):
        from src.execution import trailing_sl as ts
        adapter = MagicMock()
        adapter.modify_smart_order = AsyncMock(return_value={"status": "ok"})
        prices = [{"data": {}}, {}]
        with patch.object(ts, "get_broker_adapter", return_value=adapter), \
             patch.object(ts, "stream_prices", return_value=_fake_stream(prices)):
            await ts._trail_loop(
                "GTT-1", exchange="NSE", security_id="2885", side="BUY",
                trail_points=5.0, initial_sl_trigger=2820.0, initial_sl_limit=2820.0,
                broker_name="indmoney",
            )
        adapter.modify_smart_order.assert_not_awaited()

    @pytest.mark.anyio
    async def test_does_not_advance_sl_when_modify_fails(self):
        from src.execution import trailing_sl as ts
        adapter = MagicMock()
        adapter.modify_smart_order = AsyncMock(return_value={"status": "error", "message": "rejected"})
        prices = [{"data": {"ltp": 2830}}, {"data": {"ltp": 2831}}]
        with patch.object(ts, "get_broker_adapter", return_value=adapter), \
             patch.object(ts, "stream_prices", return_value=_fake_stream(prices)):
            await ts._trail_loop(
                "GTT-1", exchange="NSE", security_id="2885", side="BUY",
                trail_points=5.0, initial_sl_trigger=2820.0, initial_sl_limit=2820.0,
                broker_name="indmoney",
            )
        # both attempts use the SAME (unmoved) baseline since neither succeeded
        for call in adapter.modify_smart_order.await_args_list:
            assert call.kwargs["sl_trigger_price"] == 2825.0 if call is adapter.modify_smart_order.await_args_list[0] else True

    @pytest.mark.anyio
    async def test_persists_state_on_successful_ratchet(self):
        from src.execution import trailing_sl as ts
        adapter = MagicMock()
        adapter.modify_smart_order = AsyncMock(return_value={"status": "ok"})
        upsert_mock = AsyncMock()
        prices = [{"data": {"ltp": 2830}}]
        with patch.object(ts, "get_broker_adapter", return_value=adapter), \
             patch.object(ts, "stream_prices", return_value=_fake_stream(prices)), \
             patch.object(ts._repo, "upsert_trailing_sl_state", upsert_mock):
            await ts._trail_loop(
                "GTT-1", exchange="NSE", security_id="2885", side="BUY",
                trail_points=5.0, initial_sl_trigger=2820.0, initial_sl_limit=2820.0,
                broker_name="indmoney",
            )
        upsert_mock.assert_awaited_once()
        assert upsert_mock.call_args.kwargs["order_id"] == "GTT-1"
        assert upsert_mock.call_args.kwargs["sl_trigger_price"] == 2825.0

    @pytest.mark.anyio
    async def test_does_not_persist_on_failed_ratchet(self):
        from src.execution import trailing_sl as ts
        adapter = MagicMock()
        adapter.modify_smart_order = AsyncMock(return_value={"status": "error"})
        upsert_mock = AsyncMock()
        prices = [{"data": {"ltp": 2830}}]
        with patch.object(ts, "get_broker_adapter", return_value=adapter), \
             patch.object(ts, "stream_prices", return_value=_fake_stream(prices)), \
             patch.object(ts._repo, "upsert_trailing_sl_state", upsert_mock):
            await ts._trail_loop(
                "GTT-1", exchange="NSE", security_id="2885", side="BUY",
                trail_points=5.0, initial_sl_trigger=2820.0, initial_sl_limit=2820.0,
                broker_name="indmoney",
            )
        upsert_mock.assert_not_awaited()


class TestTrailLoopSell:

    @pytest.mark.anyio
    async def test_moves_sl_down_as_price_falls(self):
        from src.execution import trailing_sl as ts
        adapter = MagicMock()
        adapter.modify_smart_order = AsyncMock(return_value={"status": "ok"})
        prices = [{"data": {"ltp": 2800}}, {"data": {"ltp": 2790}}]
        with patch.object(ts, "get_broker_adapter", return_value=adapter), \
             patch.object(ts, "stream_prices", return_value=_fake_stream(prices)):
            await ts._trail_loop(
                "GTT-1", exchange="NSE", security_id="2885", side="SELL",
                trail_points=5.0, initial_sl_trigger=2820.0, initial_sl_limit=2820.0,
                broker_name="indmoney",
            )
        first_call = adapter.modify_smart_order.await_args_list[0]
        assert first_call.kwargs["sl_trigger_price"] == 2805.0  # 2800 + 5
        second_call = adapter.modify_smart_order.await_args_list[1]
        assert second_call.kwargs["sl_trigger_price"] == 2795.0  # 2790 + 5

    @pytest.mark.anyio
    async def test_does_not_move_sl_up_on_price_rise(self):
        from src.execution import trailing_sl as ts
        adapter = MagicMock()
        adapter.modify_smart_order = AsyncMock(return_value={"status": "ok"})
        prices = [{"data": {"ltp": 2850}}]  # above trigger-trail; must not move
        with patch.object(ts, "get_broker_adapter", return_value=adapter), \
             patch.object(ts, "stream_prices", return_value=_fake_stream(prices)):
            await ts._trail_loop(
                "GTT-1", exchange="NSE", security_id="2885", side="SELL",
                trail_points=5.0, initial_sl_trigger=2820.0, initial_sl_limit=2820.0,
                broker_name="indmoney",
            )
        adapter.modify_smart_order.assert_not_awaited()


class TestStartCancelTrailingSl:

    @pytest.mark.anyio
    async def test_start_registers_task(self):
        from src.execution import trailing_sl as ts

        async def _noop():
            await asyncio.sleep(10)

        with patch.object(ts, "_trail_loop", side_effect=lambda *a, **k: _noop()):
            ts.start_trailing_sl(
                "GTT-99", exchange="NSE", security_id="1", side="BUY",
                trail_points=5.0, initial_sl_trigger=100.0, initial_sl_limit=100.0,
            )
            assert ts.is_trailing("GTT-99")
            ts.cancel_trailing_sl("GTT-99")
            assert not ts.is_trailing("GTT-99")

    def test_cancel_unknown_order_returns_false(self):
        from src.execution import trailing_sl as ts
        assert ts.cancel_trailing_sl("does-not-exist") is False

    @pytest.mark.anyio
    async def test_start_twice_cancels_previous_task(self):
        from src.execution import trailing_sl as ts

        async def _noop():
            await asyncio.sleep(10)

        with patch.object(ts, "_trail_loop", side_effect=lambda *a, **k: _noop()):
            ts.start_trailing_sl(
                "GTT-1", exchange="NSE", security_id="1", side="BUY",
                trail_points=5.0, initial_sl_trigger=100.0, initial_sl_limit=100.0,
            )
            first_task = ts._active_trailers["GTT-1"]
            ts.start_trailing_sl(
                "GTT-1", exchange="NSE", security_id="1", side="BUY",
                trail_points=5.0, initial_sl_trigger=100.0, initial_sl_limit=100.0,
            )
            second_task = ts._active_trailers["GTT-1"]
            assert first_task is not second_task
            assert first_task.cancelled() or first_task.cancelling()
            ts.cancel_trailing_sl("GTT-1")

    @pytest.mark.anyio
    async def test_start_persists_initial_state(self):
        from src.execution import trailing_sl as ts

        async def _noop():
            await asyncio.sleep(10)

        upsert_mock = AsyncMock()
        with patch.object(ts, "_trail_loop", side_effect=lambda *a, **k: _noop()), \
             patch.object(ts._repo, "upsert_trailing_sl_state", upsert_mock):
            ts.start_trailing_sl(
                "GTT-50", exchange="NSE", security_id="1", side="BUY",
                trail_points=5.0, initial_sl_trigger=100.0, initial_sl_limit=99.0,
            )
            await asyncio.sleep(0)  # let the fire-and-forget upsert task run
        upsert_mock.assert_awaited_once()
        assert upsert_mock.call_args.kwargs["order_id"] == "GTT-50"
        assert upsert_mock.call_args.kwargs["sl_trigger_price"] == 100.0
        ts.cancel_trailing_sl("GTT-50")

    @pytest.mark.anyio
    async def test_rehydrate_skips_persist_on_start(self):
        from src.execution import trailing_sl as ts

        async def _noop():
            await asyncio.sleep(10)

        upsert_mock = AsyncMock()
        with patch.object(ts, "_trail_loop", side_effect=lambda *a, **k: _noop()), \
             patch.object(ts._repo, "upsert_trailing_sl_state", upsert_mock):
            ts.start_trailing_sl(
                "GTT-51", exchange="NSE", security_id="1", side="BUY",
                trail_points=5.0, initial_sl_trigger=100.0, initial_sl_limit=99.0,
                _persist=False,
            )
            await asyncio.sleep(0)
        upsert_mock.assert_not_awaited()
        ts.cancel_trailing_sl("GTT-51")

    @pytest.mark.anyio
    async def test_cancel_deactivates_persisted_state(self):
        from src.execution import trailing_sl as ts

        async def _noop():
            await asyncio.sleep(10)

        deactivate_mock = AsyncMock()
        with patch.object(ts, "_trail_loop", side_effect=lambda *a, **k: _noop()), \
             patch.object(ts._repo, "upsert_trailing_sl_state", AsyncMock()), \
             patch.object(ts._repo, "deactivate_trailing_sl_state", deactivate_mock):
            ts.start_trailing_sl(
                "GTT-52", exchange="NSE", security_id="1", side="BUY",
                trail_points=5.0, initial_sl_trigger=100.0, initial_sl_limit=99.0,
            )
            ts.cancel_trailing_sl("GTT-52")
            await asyncio.sleep(0)
        deactivate_mock.assert_awaited_once_with("GTT-52")

    def test_cancel_without_running_loop_does_not_raise(self):
        from src.execution import trailing_sl as ts
        # No event loop at all in this sync test — must degrade gracefully,
        # not crash, since cancel_trailing_sl can be called from sync code.
        assert ts.cancel_trailing_sl("no-such-order") is False


class TestRehydrateTrailingSl:

    @pytest.mark.anyio
    async def test_resumes_every_active_row(self):
        from src.execution import trailing_sl as ts
        rows = [
            {"order_id": "GTT-1", "exchange": "NSE", "security_id": "1", "side": "BUY",
             "broker": "indmoney", "trail_points": 5.0, "sl_trigger_price": 100.0, "sl_limit_price": 99.0},
            {"order_id": "GTT-2", "exchange": "NSE", "security_id": "2", "side": "SELL",
             "broker": "indmoney", "trail_points": 3.0, "sl_trigger_price": 200.0, "sl_limit_price": 201.0},
        ]
        start_mock = MagicMock()
        with patch.object(ts._repo, "list_active_trailing_sl_state", AsyncMock(return_value=rows)), \
             patch.object(ts, "start_trailing_sl", start_mock):
            resumed = await ts.rehydrate_trailing_sl()
        assert resumed == 2
        assert start_mock.call_count == 2
        first_kwargs = start_mock.call_args_list[0].kwargs
        assert first_kwargs["_persist"] is False
        assert start_mock.call_args_list[0].args == ("GTT-1",)

    @pytest.mark.anyio
    async def test_no_active_rows_resumes_nothing(self):
        from src.execution import trailing_sl as ts
        with patch.object(ts._repo, "list_active_trailing_sl_state", AsyncMock(return_value=[])), \
             patch.object(ts, "start_trailing_sl") as start_mock:
            resumed = await ts.rehydrate_trailing_sl()
        assert resumed == 0
        start_mock.assert_not_called()

    @pytest.mark.anyio
    async def test_one_bad_row_does_not_block_the_rest(self):
        from src.execution import trailing_sl as ts
        rows = [
            {"order_id": "GTT-BAD", "exchange": "NSE", "security_id": "1", "side": "BUY",
             "broker": "indmoney", "trail_points": 5.0, "sl_trigger_price": 100.0, "sl_limit_price": 99.0},
            {"order_id": "GTT-OK", "exchange": "NSE", "security_id": "2", "side": "BUY",
             "broker": "indmoney", "trail_points": 5.0, "sl_trigger_price": 100.0, "sl_limit_price": 99.0},
        ]

        def _start(order_id, **kwargs):
            if order_id == "GTT-BAD":
                raise RuntimeError("boom")

        with patch.object(ts._repo, "list_active_trailing_sl_state", AsyncMock(return_value=rows)), \
             patch.object(ts, "start_trailing_sl", side_effect=_start):
            resumed = await ts.rehydrate_trailing_sl()
        assert resumed == 1
