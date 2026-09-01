"""
InstrumentResolver — resolve a canonical symbol to INDstocks scrip-code format.

Scrip code format: {EXCHANGE}_{SECURITY_ID}  e.g. "NSE_2885", "BSE_500325"

Resolution order:
  1. KNOWN_SCRIP_CODES — instant for well-known indices
  2. Instruments CSV from INDstocks /market/instruments API (cached 24h)
  3. Return None — caller falls back to Yahoo Finance
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 86400  # 24 hours
_INSTRUMENTS_URL = "https://api.indstocks.com/market/instruments"
_TOKEN_ENV = "INDSTOCKS_TOKEN"


def _cache_path(source: str) -> str:
    tmp = os.environ.get("TMPDIR", os.environ.get("TEMP", "/tmp"))
    return os.path.join(tmp, f"indmoney_instruments_{source}.csv")


def _scrip_cache_path() -> str:
    tmp = os.environ.get("TMPDIR", os.environ.get("TEMP", "/tmp"))
    return os.path.join(tmp, "indmoney_scrip_lookup.json")


def _load_scrip_cache() -> dict | None:
    path = _scrip_cache_path()
    try:
        if not os.path.exists(path):
            return None
        if time.time() - os.path.getmtime(path) > _CACHE_TTL_SECONDS:
            return None
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _save_scrip_cache(lookup: dict) -> None:
    path = _scrip_cache_path()
    try:
        with open(path, "w") as f:
            json.dump(lookup, f)
    except Exception as exc:
        logger.debug("Failed to save scrip cache: %s", exc)


class InstrumentResolver:
    """Resolve canonical symbols to INDstocks scrip-code format."""

    # Verified fallbacks for major indices — avoids an API round-trip on cold start.
    # Security IDs may change: these are a best-effort hardcode, resolver will
    # overwrite with live data on first successful instruments fetch.
    KNOWN_SCRIP_CODES: dict[str, str] = {
        "NIFTY":       "NSE_NIFTY50",
        "NIFTY50":     "NSE_NIFTY50",
        "NIFTY 50":    "NSE_NIFTY50",
        "BANKNIFTY":   "NSE_BANKNIFTY",
        "NIFTY BANK":  "NSE_BANKNIFTY",
        "FINNIFTY":    "NSE_FINNIFTY",
        "SENSEX":      "BSE_40000006",
        "BANKEX":      "BSE_40000033",
        "BSE500":      "BSE_40000127",
        "BSEMIDCAP":   "BSE_40000041",
        "BSESMALLCAP": "BSE_40000035",
    }

    def __init__(self) -> None:
        self._token = os.environ.get(_TOKEN_ENV, "")
        # In-memory lookup table built on first fetch: SYMBOL → scrip_code
        self._lookup: dict[str, str] | None = None

    async def resolve(self, symbol: str, exchange: str = "NSE") -> str | None:
        """Return INDstocks scrip-code for `symbol`, or None if not found."""
        s = symbol.upper().strip()
        exch = exchange.upper()

        # Remove exchange prefix if present
        if ":" in s:
            exch, s = s.split(":", 1)

        # 1. Known indices — instant
        if s in self.KNOWN_SCRIP_CODES:
            return self.KNOWN_SCRIP_CODES[s]

        # 2. In-memory lookup (populated from instruments API)
        if self._lookup is None:
            self._lookup = _load_scrip_cache() or {}
            if not self._lookup:
                await self._build_lookup()

        key = f"{exch}:{s}"
        code = self._lookup.get(key) or self._lookup.get(s)
        return code

    async def _build_lookup(self) -> None:
        """Fetch instrument CSV and populate self._lookup."""
        if not self._token:
            logger.debug("InstrumentResolver: no INDSTOCKS_TOKEN, skipping instrument fetch")
            return

        lookup: dict[str, str] = {}
        headers = {"Authorization": self._token, "Content-Type": "application/json"}

        for source in ("equity", "index"):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    r = await client.get(
                        _INSTRUMENTS_URL,
                        headers=headers,
                        params={"source": source},
                    )
                if r.status_code != 200 or not r.text:
                    continue

                reader = csv.DictReader(io.StringIO(r.text))
                # Normalize fieldnames — CSV headers vary slightly
                for row in reader:
                    row_norm = {k.strip().upper(): v.strip() for k, v in row.items()}
                    sec_id = row_norm.get("SECURITY_ID") or row_norm.get("SECID") or ""
                    trading_sym = (
                        row_norm.get("TRADING_SYMBOL")
                        or row_norm.get("TRADINGSYMBOL")
                        or row_norm.get("SYMBOL")
                        or ""
                    ).upper()
                    exch_col = (
                        row_norm.get("EXCHANGE")
                        or row_norm.get("SEGMENT", "NSE")
                    ).upper().split("_")[0]

                    if not sec_id or not trading_sym:
                        continue

                    scrip_code = f"{exch_col}_{sec_id}"
                    lookup[f"{exch_col}:{trading_sym}"] = scrip_code
                    lookup[trading_sym] = scrip_code

            except Exception as exc:
                logger.debug("InstrumentResolver: error fetching %s instruments: %s", source, exc)

        if lookup:
            self._lookup = lookup
            _save_scrip_cache(lookup)
            logger.debug("InstrumentResolver: built lookup with %d entries", len(lookup))


# Module-level singleton — shared across all fetch_candles calls in a session
_resolver: InstrumentResolver | None = None


def get_resolver() -> InstrumentResolver:
    global _resolver
    if _resolver is None:
        _resolver = InstrumentResolver()
    return _resolver
