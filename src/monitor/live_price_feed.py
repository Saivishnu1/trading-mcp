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

Reuses InstrumentResolver (chart_awareness.instrument_resolver) — already the
single source of truth for symbol -> INDstocks scrip-code resolution — rather
than a second index/security-id table. stream_prices() wants
"EXCHANGE:security_id" (colon); the resolver returns "EXCHANGE_security_id"
(underscore, the REST/historical convention) — converting between the two is
just a separator swap, not a different identifier.
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


class LivePriceCache:
    """Subscribes to stream_prices() for the active instrument set and
    exposes a sync get() for poll-based checks to read instead of REST."""

    def __init__(self) -> None:
        self._prices: dict[str, tuple[float, float]] = {}  # instrument -> (ltp, monotonic_ts)
        # Exact bare-security-id -> "EXCHANGE:security_id" map, rebuilt on
        # every subscription change. NB: if two different exchanges ever
        # assign the same bare numeric id (theoretically possible, not
        # observed for the index set this cache handles today), the last one
        # built into this map wins — push messages carry no exchange field.
        self._bare_id_to_instrument: dict[str, str] = {}
        self._symbol_to_instrument: dict[str, str] = {}
        self._instruments: set[str] = set()
        self._task: asyncio.Task | None = None
        self._resolver = get_resolver()

    async def _resolve_instrument(self, symbol: str) -> str | None:
        scrip_code = await self._resolver.resolve(symbol)
        if not scrip_code or "_" not in scrip_code:
            return None
        exchange, security_id = scrip_code.split("_", 1)
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
        symbol), and restart the background stream only if that set
        actually changed. Safe to call every loop tick — a no-op when
        nothing has opened/closed."""
        symbols = list(_WATCHED_INDICES) + list(extra_symbols or [])
        new_symbol_map: dict[str, str] = {}
        for sym in dict.fromkeys(s.upper() for s in symbols if s):  # de-dup, preserve order
            instrument = await self._resolve_instrument(sym)
            if instrument:
                new_symbol_map[sym] = instrument

        new_instruments = set(new_symbol_map.values())
        if new_instruments == self._instruments:
            return

        self._symbol_to_instrument = new_symbol_map
        self._instruments = new_instruments
        self._bare_id_to_instrument = {
            instrument.split(":", 1)[1]: instrument for instrument in new_instruments
        }
        self._restart_stream()

    def _restart_stream(self) -> None:
        if self._task is not None:
            self._task.cancel()
        if not self._instruments:
            self._task = None
            return
        self._task = asyncio.create_task(self._consume(list(self._instruments)))

    async def _consume(self, instruments: list[str]) -> None:
        try:
            async for msg in stream_prices(instruments, mode="ltp"):
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
