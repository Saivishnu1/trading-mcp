"""PositionPriceCache — real-time per-position premium feed for
check_positions()'s trailing-SL / profit-milestone checks.

## The bug this replaces

PositionTracker._get_current_premium() previously called:

    adapter = get_broker_adapter(pos["broker"])
    quotes = await adapter.get_quote([pos["symbol"]])

Two independent problems made this always return no usable premium:

1. `pos["symbol"]` is the bare *underlying* name (e.g. "NIFTY"), never the
   option contract itself — PositionSymbolResolver stores symbol/expiry/
   strike/option_type as separate fields and nothing ever reassembles them
   into a quotable instrument identifier.
2. `ZerodhaBroker.get_quote()` unconditionally returns `[]` (no Kite Connect
   access on this account). `INDmoneyBroker.get_quote()` expects a
   "SEGMENT_TOKEN" scrip code (e.g. "NSE_2885"), not a bare symbol string.

So `current_premium` was effectively always `None`, and `check_positions()`
silently skipped every position (`if current_premium is None: continue`) —
trailing-SL and profit-milestone alerts never actually fired, regardless of
which broker holds the position.

## The fix

Market data for a position's *price* is independent of which broker holds
it — the same principle execution/trailing_sl.py already relies on (it
streams from INDstocks regardless of which broker placed the order, using
the broker adapter only for the order-modify call). PositionInstrumentResolver
resolves (symbol, expiry, strike, option_type, exchange) to an INDstocks
NFO:/BFO: instrument key by matching the F&O instruments CSV
(/market/instruments?source=fno) — broker-agnostic, works for Zerodha- and
INDmoney-held positions alike.

PositionPriceCache then streams LTP for every active position's resolved
instrument (same persistent-connection subscribe/unsubscribe pattern as
src/monitor/live_price_feed.py's LivePriceCache) and, critically, can
optionally fire a callback on every tick — so a stop-loss breach or profit
target is checked the moment a price update arrives, not only at the next
poll tick. A position that can't be resolved (F&O CSV miss, or malformed
data) is never silently invented a fake price for — get() returns None and
the caller falls back to its existing REST path, same failure mode as
before this module existed, just with the underlying bug also fixed there.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from datetime import date, datetime

from src.brokers.indmoney import INDmoneyBroker
from src.brokers.streaming import stream_prices

logger = logging.getLogger(__name__)

_MAX_STALENESS_SECONDS = 30.0
_FNO_CACHE_TTL_SECONDS = 86400  # 24 hours — matches InstrumentResolver's convention

# WS instrument segment per exchange for F&O (see api-docs.indstocks.com/Websockets/):
# NSE Derivatives -> NFO:, BSE Derivatives -> BFO:. Distinct from the NIDX:/BIDX:
# index segments live_price_feed.py handles, and from the plain NSE:/BSE:
# equity segment — this module is F&O-only.
_EXCHANGE_TO_FNO_SEGMENT: dict[str, str] = {"NSE": "NFO", "BSE": "BFO"}


def _fno_cache_path() -> str:
    tmp = os.environ.get("TMPDIR", os.environ.get("TEMP", "/tmp"))
    return os.path.join(tmp, "indmoney_fno_instruments_cache.json")


def _load_disk_cache() -> list[dict] | None:
    path = _fno_cache_path()
    try:
        if not os.path.exists(path):
            return None
        if time.time() - os.path.getmtime(path) > _FNO_CACHE_TTL_SECONDS:
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_disk_cache(rows: list[dict]) -> None:
    try:
        with open(_fno_cache_path(), "w", encoding="utf-8") as f:
            json.dump(rows, f)
    except Exception as exc:
        logger.debug("Failed to save F&O instrument cache: %s", exc)


def _parse_date_loose(raw: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _expiry_matches(row_expiry_raw: str, pos_expiry: str) -> bool:
    """Compare a CSV row's expiry against a position's stored expiry.

    Zerodha *monthly* contracts encode only year+month in pos["expiry"]
    (day forced to "01" — see symbol_resolver._parse_zerodha_tradingsymbol's
    docstring: "monthly contracts: exact day not encoded"). There is at most
    one monthly expiry per underlying+strike+option_type per month, so
    falling back to a year/month-only comparison in that case is safe and
    correct, not just a loose approximation.
    """
    pos_date = _parse_date_loose(pos_expiry)
    row_date = _parse_date_loose(row_expiry_raw)
    if pos_date is None or row_date is None:
        return False
    if pos_date.day == 1:
        return (pos_date.year, pos_date.month) == (row_date.year, row_date.month)
    return pos_date == row_date


class PositionInstrumentResolver:
    """Resolve an open option position to its INDstocks WS instrument key by
    matching the F&O instruments CSV. Broker-agnostic — this is a
    market-data lookup, not an order-execution one."""

    def __init__(self) -> None:
        self._rows: list[dict] | None = None
        self._rows_loaded_at: float | None = None

    async def _ensure_rows(self) -> list[dict]:
        now = time.monotonic()
        if self._rows is not None and self._rows_loaded_at is not None:
            if now - self._rows_loaded_at < _FNO_CACHE_TTL_SECONDS:
                return self._rows

        cached = _load_disk_cache()
        if cached is not None:
            self._rows = cached
            self._rows_loaded_at = now
            return self._rows

        rows = await INDmoneyBroker().get_instruments(source="fno")
        self._rows = rows
        self._rows_loaded_at = now
        if rows:
            _save_disk_cache(rows)
        return rows

    @staticmethod
    def _row_matches(row: dict, symbol: str, expiry: str, strike: float, option_type: str) -> bool:
        row_symbol = (row.get("underlying_symbol") or row.get("name") or "").strip().upper()
        if row_symbol != symbol.strip().upper():
            return False
        row_opt = (row.get("option_type") or row.get("instrument_type") or "").strip().upper()
        if row_opt != option_type.strip().upper():
            return False
        try:
            row_strike = float(row.get("strike_price") or row.get("strike") or 0)
        except (TypeError, ValueError):
            return False
        if abs(row_strike - float(strike)) > 0.01:
            return False
        row_expiry_raw = row.get("expiry") or row.get("expiry_date") or ""
        if not row_expiry_raw:
            return False
        return _expiry_matches(row_expiry_raw, expiry)

    async def resolve(
        self, *, symbol: str, expiry: str, strike: float, option_type: str, exchange: str = "NSE",
    ) -> str | None:
        segment = _EXCHANGE_TO_FNO_SEGMENT.get((exchange or "NSE").upper())
        if segment is None:
            return None
        rows = await self._ensure_rows()
        for row in rows:
            if not isinstance(row, dict):
                continue
            if self._row_matches(row, symbol, expiry, strike, option_type):
                security_id = row.get("security_id") or row.get("scrip_code") or row.get("token")
                if security_id:
                    return f"{segment}:{security_id}"
        return None


# Module-level singleton — the F&O CSV lookup is expensive to rebuild and
# shared across every position, same convention as
# chart_awareness.instrument_resolver.get_resolver().
_resolver: PositionInstrumentResolver | None = None


def get_position_instrument_resolver() -> PositionInstrumentResolver:
    global _resolver
    if _resolver is None:
        _resolver = PositionInstrumentResolver()
    return _resolver


PriceTickCallback = Callable[[str, float], Awaitable[None]]


class PositionPriceCache:
    """Streams live LTP for every active position's option contract.

    Keyed by position id (not symbol — two positions can share the same
    underlying/expiry/strike/option_type is impossible by the unique
    constraint on monitor.positions, but keying by id keeps this
    unambiguous regardless). An optional on_tick callback fires on every
    price update for a subscribed position, so a caller can check
    SL/profit-milestone conditions the moment a tick arrives instead of
    only at the next poll — on_tick exceptions are logged and never
    propagate, so one bad check must not kill the stream.
    """

    def __init__(self, on_tick: PriceTickCallback | None = None) -> None:
        self._prices: dict[str, tuple[float, float]] = {}  # instrument -> (ltp, monotonic_ts)
        self._position_to_instrument: dict[str, str] = {}  # position_id -> instrument
        self._bare_id_to_instrument: dict[str, str] = {}
        self._instruments: set[str] = set()
        self._task: asyncio.Task | None = None
        self._updates: asyncio.Queue | None = None
        self._resolver = get_position_instrument_resolver()
        self._on_tick = on_tick

    def get(self, position_id: str) -> float | None:
        instrument = self._position_to_instrument.get(position_id)
        if instrument is None:
            return None
        entry = self._prices.get(instrument)
        if entry is None:
            return None
        ltp, ts = entry
        if time.monotonic() - ts > _MAX_STALENESS_SECONDS:
            return None
        return ltp

    async def refresh_subscriptions(self, positions: list[dict]) -> None:
        """Recompute the instrument set from the given active positions
        (each needs "id"/"symbol"/"expiry"/"strike"/"option_type", and
        optionally "exchange"). Safe to call every check_positions() tick —
        a no-op when the position set hasn't changed."""
        new_position_map: dict[str, str] = {}
        for pos in positions:
            instrument = await self._resolver.resolve(
                symbol=pos["symbol"], expiry=pos["expiry"], strike=pos["strike"],
                option_type=pos["option_type"], exchange=pos.get("exchange", "NSE"),
            )
            if instrument:
                new_position_map[pos["id"]] = instrument

        new_instruments = set(new_position_map.values())
        old_instruments = self._instruments
        if new_instruments == old_instruments:
            self._position_to_instrument = new_position_map  # ids can still change
            return

        added = new_instruments - old_instruments
        removed = old_instruments - new_instruments

        self._position_to_instrument = new_position_map
        self._instruments = new_instruments
        self._bare_id_to_instrument = {
            instrument.split(":", 1)[1]: instrument for instrument in new_instruments
        }
        for instrument in removed:
            self._prices.pop(instrument, None)

        if self._task is None:
            if not new_instruments:
                return
            self._updates = asyncio.Queue()
            self._task = asyncio.create_task(self._consume(list(new_instruments)))
            return

        # _task and _updates are always set together (see the branch
        # above), so _task being non-None here guarantees _updates is too.
        assert self._updates is not None
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
                    ltp_f = float(ltp)
                except (TypeError, ValueError):
                    continue
                self._prices[instrument] = (ltp_f, time.monotonic())

                if self._on_tick is not None:
                    position_ids = [
                        pid for pid, inst in self._position_to_instrument.items()
                        if inst == instrument
                    ]
                    for pid in position_ids:
                        try:
                            await self._on_tick(pid, ltp_f)
                        except Exception as exc:
                            logger.warning("PositionPriceCache on_tick failed for %s: %s", pid, exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("PositionPriceCache._consume stream error: %s", exc)

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
            self._updates = None
