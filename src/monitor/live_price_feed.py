"""LivePriceCache — background WS price feed for the monitor's poll-based checks.

Today check_market_conditions() (scheduler.py) makes one REST option-chain
call per poll tick just to read the embedded spot price for NIFTY/SENSEX.
This module gives it an always-warm in-memory alternative: subscribe once to
src.brokers.streaming.stream_prices() for whatever indices/positions are
active right now, and let callers read the latest pushed price synchronously
instead of making a fresh REST round trip at check time.

Isolation: this is a self-contained module. It only changes where
scheduler.py's checks *read* the current price from — conditions.py,
market_intelligence.py, order placement, the order-update listener, and
trailing_sl.py are untouched. A cache miss (no data yet, e.g. a subscription
that was just added) or a stale entry (WS silently died) must never mean "the
check doesn't run" — get() returns None in that case and the caller falls
back to its existing REST path, same as before this module existed.

One persistent connection, dynamic subscriptions (confirmed against
api-docs.indstocks.com/Websockets/, 2026-07-11): the price feed's `action`
is `"subscribe"` or `"unsubscribe"`, sent as an ordinary message on an
already-open connection — not a new one. stream_prices() exposes this via an
optional `subscription_updates` queue (src/brokers/streaming.py). This cache
starts the stream once (on the first non-empty refresh_subscriptions call)
and pushes incremental subscribe/unsubscribe messages as positions open and
close, instead of reconnecting on every change.

Instrument format — TWO DIFFERENT SEGMENT NAMESPACES, do not conflate them:
  NSE/BSE equity   "NSE:security_id" / "BSE:security_id"  (numeric, e.g. "NSE:2885")
                   — identical security_id in both this WS feed and
                   InstrumentResolver's REST scrip-code convention
                   ("NSE_2885"); just a separator swap.
  NSE/BSE index    "NIDX:token" / "BIDX:token"             (e.g. "NIDX:26000")
                   — a *different* segment from equities. InstrumentResolver's
                   KNOWN_SCRIP_CODES table ("NSE_NIFTY50", "BSE_40000006", ...)
                   is the REST/historical-API convention and does NOT apply
                   here; reusing it for indices (an earlier version of this
                   file did) silently subscribes to the wrong instrument.
                   _INDEX_WS_TOKENS below is the price-feed-specific mapping.
"""
from __future__ import annotations

import asyncio
import logging
import time

from src.brokers.streaming import stream_prices
from src.chart_awareness.instrument_resolver import get_resolver

logger = logging.getLogger(__name__)

# Indices every wall-break/PCR/index-move check depends on today
# (market_intelligence.py's nifty_spot/sensex_spot), independent of whatever
# positions happen to be open right now.
_WATCHED_INDICES = ("NIFTY", "SENSEX")

# Beyond this age a cached price is treated as if it were never subscribed —
# a silently-dead WS subscription must fall back to REST, not serve a
# stale value forever.
_MAX_STALENESS_SECONDS = 30.0

# WS price-feed index tokens — NIDX:/BIDX:, a different namespace from
# InstrumentResolver's scrip codes (NSE_/BSE_). NIFTY (26000) and SENSEX (1)
# are api-docs.indstocks.com/Websockets/'s own worked examples for the
# NIDX:/BIDX: format, and match the token every major Indian broker API
# assigns to these two indices. BANKNIFTY/FINNIFTY/MIDCPNIFTY are the
# standard NSE index tokens seen across other broker docs but NOT
# independently confirmed against INDstocks' docs — verify against a live
# tick before relying on these three. BANKEX has no confirmed token and is
# deliberately left out entirely: an unresolvable symbol here just means
# "cache stays empty for it, REST fallback used," which is always safe —
# guessing a wrong token would not be.
_INDEX_WS_TOKENS: dict[str, str] = {
    "NIFTY":      "NIDX:26000",
    "SENSEX":     "BIDX:1",
    "BANKNIFTY":  "NIDX:26009",   # cross-broker standard, unverified vs INDstocks docs
    "FINNIFTY":   "NIDX:26037",   # cross-broker standard, unverified vs INDstocks docs
    "MIDCPNIFTY": "NIDX:26074",   # cross-broker standard, unverified vs INDstocks docs
}


class LivePriceCache:
    """Subscribes to stream_prices() for the active instrument set and
    exposes a sync get() for poll-based checks to read instead of REST."""

    def __init__(self) -> None:
        self._prices: dict[str, tuple[float, float]] = {}  # instrument -> (ltp, monotonic_ts)
        # Exact bare-security-id/token -> "SEGMENT:id" map, rebuilt on every
        # subscription change. NB: if two different segments ever assign the
        # same bare id (not observed for the index/equity set this cache
        # handles today), the last one built into this map wins — push
        # messages carry no segment field, only the bare id.
        self._bare_id_to_instrument: dict[str, str] = {}
        self._symbol_to_instrument: dict[str, str] = {}
        self._instruments: set[str] = set()
        self._task: asyncio.Task | None = None
        self._updates: asyncio.Queue | None = None
        self._resolver = get_resolver()

    async def _resolve_instrument(self, symbol: str) -> str | None:
        sym = symbol.upper()
        if sym in _INDEX_WS_TOKENS:
            return _INDEX_WS_TOKENS[sym]
        if sym in self._resolver.KNOWN_SCRIP_CODES:
            # A known index without a verified NIDX:/BIDX: token (e.g.
            # BANKEX) — every entry in KNOWN_SCRIP_CODES is an index, never
            # an equity (see instrument_resolver.py). Do NOT fall through to
            # the REST scrip-code path below for these: it uses NSE_/BSE_,
            # the wrong segment for an index on this WS feed, and would
            # silently subscribe to a garbage or unrelated instrument.
            return None

        # Equities only, from here down — NSE:/BSE: with a numeric
        # security_id is identical in both the REST scrip-code convention
        # and the WS price feed, so a straight separator swap is correct.
        scrip_code = await self._resolver.resolve(sym)
        if not scrip_code or "_" not in scrip_code:
            return None
        exchange, security_id = scrip_code.split("_", 1)
        if exchange not in ("NSE", "BSE"):
            return None
        return f"{exchange}:{security_id}"

    def get(self, symbol: str) -> float | None:
        """Return the latest streamed LTP for `symbol`, or None if there is
        no value yet or the last push is older than _MAX_STALENESS_SECONDS."""
        instrument = self._symbol_to_instrument.get(symbol.upper())
        if instrument is None:
            return None
        entry = self._prices.get(instrument)
        if entry is None:
            return None
        ltp, ts = entry
        if time.monotonic() - ts > _MAX_STALENESS_SECONDS:
            return None
        return ltp

    async def refresh_subscriptions(self, extra_symbols: list[str] | None = None) -> None:
        """Recompute the instrument set from the watched indices plus
        `extra_symbols` (typically each active position's underlying
        symbol). On the first call this starts one persistent stream; every
        later change sends incremental subscribe/unsubscribe messages on
        that same connection (no reconnect) — safe to call every loop tick,
        a no-op when nothing has opened/closed."""
        symbols = list(_WATCHED_INDICES) + list(extra_symbols or [])
        new_symbol_map: dict[str, str] = {}
        for sym in dict.fromkeys(s.upper() for s in symbols if s):  # de-dup, preserve order
            instrument = await self._resolve_instrument(sym)
            if instrument:
                new_symbol_map[sym] = instrument

        new_instruments = set(new_symbol_map.values())
        old_instruments = self._instruments
        if new_instruments == old_instruments:
            return

        added = new_instruments - old_instruments
        removed = old_instruments - new_instruments

        self._symbol_to_instrument = new_symbol_map
        self._instruments = new_instruments
        self._bare_id_to_instrument = {
            instrument.split(":", 1)[1]: instrument for instrument in new_instruments
        }
        for instrument in removed:
            self._prices.pop(instrument, None)

        if self._task is None:
            if not new_instruments:
                return
            # First activation — one persistent connection, plus a live
            # update queue so every later change is a subscribe/unsubscribe
            # message on this same connection, never a reconnect.
            self._updates = asyncio.Queue()
            self._task = asyncio.create_task(self._consume(list(new_instruments)))
            return

        if added:
            await self._updates.put({
                "action": "subscribe", "mode": "ltp", "instruments": sorted(added),
            })
        if removed:
            await self._updates.put({
                "action": "unsubscribe", "mode": "ltp", "instruments": sorted(removed),
            })

    async def _consume(self, initial_instruments: list[str]) -> None:
        try:
            async for msg in stream_prices(
                initial_instruments, mode="ltp", subscription_updates=self._updates,
            ):
                if not isinstance(msg, dict):
                    continue
                bare_id = msg.get("instrument")
                data = msg.get("data")
                ltp = data.get("ltp") if isinstance(data, dict) else None
                if bare_id is None or ltp is None:
                    continue
                instrument = self._bare_id_to_instrument.get(str(bare_id))
                if instrument is None:
                    continue
                try:
                    self._prices[instrument] = (float(ltp), time.monotonic())
                except (TypeError, ValueError):
                    continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("LivePriceCache._consume stream error: %s", exc)

    def stop(self) -> None:
        """Cancel the background stream task, if any. Not called by the
        monitor's main loop today (the process only exits via SIGTERM/crash),
        but kept for symmetry with start and for tests."""
        if self._task is not None:
            self._task.cancel()
            self._task = None
            self._updates = None
