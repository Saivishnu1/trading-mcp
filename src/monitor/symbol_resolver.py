"""Resolve a broker's raw option instrument identifier to a normalized dict:

    {"symbol": "NIFTY", "expiry": "2026-07-09", "strike": 24400.0,
     "option_type": "CE", "exchange": "NSE"}

Layered lookup: in-memory cache -> monitor.instrument_cache (Postgres, TTL via
expires_at, refreshed daily on each cache write) -> broker-specific resolution
(Zerodha: parse tradingsymbol; INDmoney: match against the
/market/instruments?source=fno CSV).
"""
from __future__ import annotations

import logging
import re

from src.monitor.repository import MonitorRepository

logger = logging.getLogger(__name__)

# Zerodha NFO tradingsymbol format: NIFTY26JUL24400CE / NIFTY2670924400CE (weekly)
_ZERODHA_MONTHLY_RE = re.compile(r"^([A-Z]+)(\d{2})([A-Z]{3})(\d+(?:\.\d+)?)(CE|PE)$")
_ZERODHA_WEEKLY_RE = re.compile(r"^([A-Z]+)(\d{2})(\d)(\d{2})(\d+(?:\.\d+)?)(CE|PE)$")
_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _parse_zerodha_tradingsymbol(tradingsymbol: str) -> dict | None:
    """Parse NFO tradingsymbol without an instruments CSV — Zerodha embeds
    symbol/expiry/strike/option_type directly in the string."""
    m = _ZERODHA_MONTHLY_RE.match(tradingsymbol)
    if m:
        symbol, yy, mon, strike, opt = m.groups()
        month = _MONTH_MAP.get(mon)
        if month is None:
            return None
        year = 2000 + int(yy)
        return {
            "symbol": symbol,
            "expiry": f"{year:04d}-{month:02d}-01",  # monthly contracts: exact day not encoded
            "strike": float(strike),
            "option_type": opt,
            "exchange": "NSE",
        }
    m = _ZERODHA_WEEKLY_RE.match(tradingsymbol)
    if m:
        symbol, yy, mon_digit, dd, strike, opt = m.groups()
        year = 2000 + int(yy)
        month = int(mon_digit)
        return {
            "symbol": symbol,
            "expiry": f"{year:04d}-{month:02d}-{int(dd):02d}",
            "strike": float(strike),
            "option_type": opt,
            "exchange": "NSE",
        }
    return None


def _match_indmoney_row(row: dict, instrument_id: str) -> bool:
    return (
        row.get("security_id") == instrument_id
        or row.get("scrip_code") == instrument_id
        or row.get("token") == instrument_id
    )


def _normalize_indmoney_row(row: dict) -> dict | None:
    try:
        expiry_raw = row.get("expiry") or row.get("expiry_date") or ""
        strike = float(row.get("strike_price") or row.get("strike") or 0)
        opt = (row.get("option_type") or row.get("instrument_type") or "").upper()
        if opt not in ("CE", "PE"):
            return None
        return {
            "symbol": row.get("underlying_symbol") or row.get("name") or "",
            "expiry": expiry_raw,
            "strike": strike,
            "option_type": opt,
            "exchange": (row.get("exchange") or "NSE").split("_")[0],
        }
    except (ValueError, TypeError):
        return None


class PositionSymbolResolver:

    def __init__(self, repo: MonitorRepository | None = None):
        self.repo = repo or MonitorRepository()
        self.memory_cache: dict[str, dict] = {}

    def _cache_key(self, broker: str, instrument_id: str) -> str:
        return f"{broker}:{instrument_id}"

    async def resolve(self, broker: str, instrument_id: str) -> dict | None:
        key = self._cache_key(broker, instrument_id)
        if key in self.memory_cache:
            return self.memory_cache[key]

        # get_cached_instrument() returns None for both "never cached" and
        # "past expires_at" — either way we fall through and re-resolve.
        cached = await self.repo.get_cached_instrument(broker, instrument_id)
        if cached is not None:
            self.memory_cache[key] = cached
            return cached

        resolved: dict | None = None
        if broker == "zerodha":
            resolved = _parse_zerodha_tradingsymbol(instrument_id)
        elif broker == "indmoney":
            resolved = await self._resolve_indmoney(instrument_id)

        if resolved is None:
            logger.warning("Could not resolve instrument %s for broker %s", instrument_id, broker)
            return None

        await self.repo.cache_instrument(broker, instrument_id, resolved)
        self.memory_cache[key] = resolved
        return resolved

    async def _resolve_indmoney(self, instrument_id: str) -> dict | None:
        from src.brokers.indmoney import INDmoneyBroker
        broker = INDmoneyBroker()
        rows = await broker.get_instruments(source="fno")
        for row in rows:
            if _match_indmoney_row(row, instrument_id):
                return _normalize_indmoney_row(row)
        return None

    async def resolve_batch(self, broker: str, instrument_ids: list[str]) -> dict[str, dict]:
        results: dict[str, dict] = {}
        misses: list[str] = []
        for iid in instrument_ids:
            key = self._cache_key(broker, iid)
            if key in self.memory_cache:
                results[iid] = self.memory_cache[key]
            else:
                misses.append(iid)

        if not misses:
            return results

        if broker == "indmoney":
            from src.brokers.indmoney import INDmoneyBroker
            ind_broker = INDmoneyBroker()
            rows = await ind_broker.get_instruments(source="fno")
            for iid in misses:
                found = next((r for r in rows if _match_indmoney_row(r, iid)), None)
                resolved = _normalize_indmoney_row(found) if found else None
                if resolved:
                    await self.repo.cache_instrument(broker, iid, resolved)
                    self.memory_cache[self._cache_key(broker, iid)] = resolved
                    results[iid] = resolved
        else:
            for iid in misses:
                resolved = await self.resolve(broker, iid)
                if resolved:
                    results[iid] = resolved

        return results
