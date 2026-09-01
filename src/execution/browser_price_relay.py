"""Browser-facing live price relay — fans one shared INDstocks WS connection
out to any number of connected browser tabs, without ever handing the
browser the real INDSTOCKS_TOKEN.

Why a relay instead of letting the browser talk to INDstocks directly: the
INDstocks token is a full-privilege credential (read account data, place
orders) and INDstocks has no scoped/short-lived token variant (confirmed
2026-07-12 against api-docs.indstocks.com — no token/scope/session
endpoint exists). Handing it to browser JS would mean anyone with devtools
access, a malicious extension, or a leaked network log could place orders.
The server already holds this token for every other write — it should be
the only thing that ever does.

Design: one process-wide BrowserPriceRelay, built on the same
subscription-queue primitive as src.monitor.live_price_feed.LivePriceCache
(src.brokers.streaming.stream_prices) — a single upstream connection,
dynamic subscribe/unsubscribe, no per-tab upstream connections. Each browser
WebSocket registers interest in a set of instruments (e.g. every open
position's "EXCHANGE:security_id"); the relay's fan-out loop pushes each
upstream tick to every registered browser socket that's subscribed to it.
Reference counting means the upstream subscription for an instrument is only
dropped once the last interested browser tab disconnects — a second tab
watching the same symbol doesn't pay a second subscribe/unsubscribe round
trip.
"""
from __future__ import annotations

import asyncio
import logging
import time

from src.brokers.streaming import stream_prices

logger = logging.getLogger(__name__)

_MAX_STALENESS_SECONDS = 30.0


class _Subscriber:
    """One connected browser tab's interest set + outbound queue. The relay
    pushes ticks onto `queue`; the route handler owns draining it to the
    actual WebSocket send() — kept separate so a slow/stuck browser socket
    can't block the relay's fan-out loop for every other tab."""

    __slots__ = ("instruments", "queue")

    def __init__(self) -> None:
        self.instruments: set[str] = set()
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)


class BrowserPriceRelay:
    """Process-wide singleton (see get_relay()). Reuse across all browser
    WebSocket connections — do not construct one per connection."""

    def __init__(self) -> None:
        self._subscribers: dict[int, _Subscriber] = {}
        self._next_id = 0
        self._instrument_refcount: dict[str, int] = {}
        self._task: asyncio.Task | None = None
        self._updates: asyncio.Queue | None = None
        self._prices: dict[str, tuple[float, float]] = {}

    def snapshot(self, instrument: str) -> float | None:
        """Return the last known LTP for `instrument`, or None if there is
        none yet or it's older than _MAX_STALENESS_SECONDS — lets a newly
        connected tab render something immediately instead of a blank
        row until the next tick arrives."""
        entry = self._prices.get(instrument)
        if entry is None:
            return None
        ltp, ts = entry
        if time.monotonic() - ts > _MAX_STALENESS_SECONDS:
            return None
        return ltp

    async def register(self, instruments: list[str]) -> tuple[int, asyncio.Queue[dict]]:
        """Register a new browser subscriber for `instruments`. Returns
        (subscriber_id, queue) — the caller reads ticks from `queue` and
        must call unregister(subscriber_id) when the connection closes."""
        sub = _Subscriber()
        sub.instruments = set(instruments)
        sub_id = self._next_id
        self._next_id += 1
        self._subscribers[sub_id] = sub
        await self._add_refs(sub.instruments)
        return sub_id, sub.queue

    async def unregister(self, sub_id: int) -> None:
        sub = self._subscribers.pop(sub_id, None)
        if sub is None:
            return
        await self._release_refs(sub.instruments)

    async def _add_refs(self, instruments: set[str]) -> None:
        new_instruments = []
        for inst in instruments:
            count = self._instrument_refcount.get(inst, 0)
            self._instrument_refcount[inst] = count + 1
            if count == 0:
                new_instruments.append(inst)
        if new_instruments:
            await self._ensure_subscribed(new_instruments)

    async def _release_refs(self, instruments: set[str]) -> None:
        removed_instruments = []
        for inst in instruments:
            count = self._instrument_refcount.get(inst, 0)
            if count <= 1:
                self._instrument_refcount.pop(inst, None)
                self._prices.pop(inst, None)
                removed_instruments.append(inst)
            else:
                self._instrument_refcount[inst] = count - 1
        if removed_instruments and self._updates is not None:
            await self._updates.put({
                "action": "unsubscribe", "mode": "ltp", "instruments": sorted(removed_instruments),
            })

    async def _ensure_subscribed(self, instruments: list[str]) -> None:
        if self._task is None:
            self._updates = asyncio.Queue()
            self._task = asyncio.create_task(self._consume(instruments))
            return
        # _task and _updates are always set together (see the branch
        # above), so _task being non-None here guarantees _updates is too.
        assert self._updates is not None
        await self._updates.put({"action": "subscribe", "mode": "ltp", "instruments": sorted(instruments)})

    async def _consume(self, initial_instruments: list[str]) -> None:
        """Run the upstream stream_prices() loop until it exits (which, per
        that generator's own contract, should only happen on cancellation --
        it reconnects forever on any connection drop internally). This
        method's own `finally` still resets self._task/_updates to None
        unconditionally, so that IF _consume ever does return/raise for a
        reason stream_prices() didn't already retry internally (an
        exception raised before the first `websockets.connect()` even
        starts, e.g. a DNS failure or a synchronous auth-header error --
        confirmed reproducible via a direct unit test), the relay can
        restart on the NEXT subscriber instead of being silently, invisibly
        dead in self._task for the rest of the process's uptime.

        This exact bug was confirmed live: once _consume exited via its own
        `except Exception` below (added originally so one bad message
        wouldn't crash the fan-out loop), self._task stayed set to the now-
        completed task forever, so _ensure_subscribed's `if self._task is
        None` check never re-triggered for any later subscriber -- every
        new browser tab, page reload, or symbol pick just pushed a
        "subscribe" message into a self._updates queue that nothing was
        reading anymore. The relay looked "connected" (the WS handshake to
        the BROWSER always succeeds) but silently never delivered another
        tick, matching the exact reported symptom: badge says Live, price
        never updates, during actual market hours."""
        try:
            async for msg in stream_prices(initial_instruments, mode="ltp", subscription_updates=self._updates):
                if not isinstance(msg, dict):
                    continue
                bare_id = msg.get("instrument")
                data = msg.get("data")
                ltp = data.get("ltp") if isinstance(data, dict) else None
                if bare_id is None or ltp is None:
                    continue
                try:
                    ltp_f = float(ltp)
                except (TypeError, ValueError):
                    continue
                # Push messages carry only the bare id, not the "EXCHANGE:id"
                # instrument key — match against every currently-tracked
                # instrument ending in this id (mirrors LivePriceCache's
                # bare_id_to_instrument approach, but our instrument set
                # changes per-subscriber so we search live refcounts instead
                # of maintaining a second reverse map that would need to stay
                # in sync across every register/unregister call).
                matches = [inst for inst in self._instrument_refcount if inst.endswith(f":{bare_id}")]
                for instrument in matches:
                    self._prices[instrument] = (ltp_f, time.monotonic())
                    await self._fan_out(instrument, ltp_f)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("BrowserPriceRelay._consume stream error: %s", exc)
        finally:
            # Only clear if we're still the task of record -- a stale
            # cancelled task from a previous, already-superseded _consume
            # run must not clobber a newer one's state (defensive; current
            # callers never overlap two live _consume tasks, but this keeps
            # the invariant true even if that ever changes).
            if self._task is asyncio.current_task():
                self._task = None
                self._updates = None

    async def _fan_out(self, instrument: str, ltp: float) -> None:
        tick = {"instrument": instrument, "ltp": ltp}
        for sub in list(self._subscribers.values()):
            if instrument not in sub.instruments:
                continue
            try:
                sub.queue.put_nowait(tick)
            except asyncio.QueueFull:
                # A stuck/slow browser tab must not back up the shared
                # upstream stream for everyone else — drop the tick for this
                # subscriber only; the next one will still arrive.
                logger.debug("BrowserPriceRelay: dropping tick for a slow subscriber (%s)", instrument)


_relay: BrowserPriceRelay | None = None


def get_relay() -> BrowserPriceRelay:
    global _relay
    if _relay is None:
        _relay = BrowserPriceRelay()
    return _relay
