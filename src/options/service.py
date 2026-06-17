"""
NSE index option chain fetcher.

Primary source: jugaad-data's NSELive.index_option_chain — works reliably from
datacenter IPs where NSE soft-blocks its public JSON API (returns an empty {}).
This is the same library the market-data service already uses for live quotes.

Fallback: direct httpx to NSE's /api/option-chain-v3 endpoint, with browser-like
cookie priming via the /option-chain page (the bare homepage often 403s).

Results are cached for 60 seconds. No authentication required.
"""

import logging
import threading
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_NSE_BASE = "https://www.nseindia.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/option-chain",
    "X-Requested-With": "XMLHttpRequest",
}
_CACHE_TTL = 60  # seconds

# NSE index symbols supported by the option-chain endpoint.
_SUPPORTED = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}


class OptionsService:
    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=_NSE_BASE,
            headers=_HEADERS,
            follow_redirects=True,
            timeout=20.0,
        )
        self._cache: dict[tuple[str, Optional[str]], tuple[dict, float]] = {}
        self._lock = threading.Lock()
        self._cookies_ready = False
        self._nse_live = None  # jugaad_data.nse.NSELive, imported lazily

    # ------------------------------------------------------------------
    # Source 1 — jugaad-data NSELive (primary)
    # ------------------------------------------------------------------

    def _get_nse_live(self):
        if self._nse_live is None:
            try:
                from jugaad_data.nse import NSELive  # type: ignore[import]
                self._nse_live = NSELive()
            except Exception as exc:
                logger.warning("jugaad-data NSELive unavailable: %s", exc)
                self._nse_live = False  # sentinel: tried and failed
        return self._nse_live if self._nse_live is not False else None

    def _is_index_symbol(self, symbol: str) -> bool:
        return symbol.upper() in _SUPPORTED

    def _fetch_via_jugaad(self, symbol: str, expiry: Optional[str] = None) -> dict | None:
        nse = self._get_nse_live()
        if nse is None:
            return None
        try:
            if self._is_index_symbol(symbol):
                return nse.index_option_chain(symbol, expiry=expiry)
            return nse.equities_option_chain(symbol, expiry=expiry)
        except Exception as exc:
            logger.debug(
                "NSELive option chain fetch failed for %s expiry=%s: %s",
                symbol,
                expiry,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Source 2 — direct httpx to option-chain-v3 (fallback)
    # ------------------------------------------------------------------

    def _prime_cookies(self) -> None:
        """NSE's API needs session cookies set by loading the option-chain page."""
        if self._cookies_ready:
            return
        try:
            self._client.get("/option-chain")
            self._client.get("/")
            self._cookies_ready = True
            logger.debug("NSE cookies primed")
        except Exception as exc:
            logger.warning("NSE cookie prime failed: %s", exc)

    def _fetch_via_httpx(self, symbol: str, expiry: Optional[str] = None) -> dict | None:
        self._prime_cookies()
        try:
            option_type = "Indices" if self._is_index_symbol(symbol) else "Equity"
            params = {"type": option_type, "symbol": symbol}
            if expiry:
                params["expiry"] = expiry
            r = self._client.get("/api/option-chain-v3", params=params)
            r.raise_for_status()
            data = r.json()
            if not data.get("records", {}).get("data"):
                logger.warning(
                    "NSE v3 endpoint returned no data for %s expiry=%s "
                    "(likely IP soft-block).",
                    symbol,
                    expiry,
                )
                return None
            return data
        except Exception as exc:
            logger.debug("httpx v3 fetch for %s expiry=%s failed: %s", symbol, expiry, exc)
            return None

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(data: dict) -> dict:
        """Give every strike row a consistent row-level 'expiryDate'.

        jugaad-data exposes it as 'expiryDates' (plural); the direct API uses
        'expiryDate' (singular). Analytics and tools filter on 'expiryDate'.
        """
        for row in data.get("records", {}).get("data", []):
            if not row.get("expiryDate"):
                row["expiryDate"] = row.get("expiryDates")
        return data

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_option_chain(self, symbol: str, expiry: Optional[str] = None) -> dict:
        """Return the normalised NSE option chain for *symbol*.

        Tries jugaad-data NSELive first, then the direct v3 endpoint.
        Cached for 60 seconds. Thread-safe.
        """
        symbol = symbol.upper()
        cache_key = (symbol, expiry)

        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and (time.monotonic() - cached[1]) < _CACHE_TTL:
                logger.debug("Option chain cache hit for %s expiry=%s", symbol, expiry)
                return cached[0]

        data = self._fetch_via_jugaad(symbol, expiry)
        if not data or not data.get("records", {}).get("data"):
            logger.info(
                "jugaad path empty for %s expiry=%s; trying direct httpx v3",
                symbol,
                expiry,
            )
            data = self._fetch_via_httpx(symbol, expiry)

        if not data or not data.get("records", {}).get("data"):
            raise RuntimeError(
                f"Could not fetch option chain for {symbol} expiry={expiry or 'default'} from any source "
                "(NSELive empty and NSE API soft-blocked). Try again shortly."
            )

        data = self._normalize(data)

        with self._lock:
            self._cache[cache_key] = (data, time.monotonic())

        return data

    def available_expiries(self, symbol: str) -> list[str]:
        """Return the list of expiry date strings for *symbol*."""
        chain = self.get_option_chain(symbol)
        return chain.get("records", {}).get("expiryDates", [])

    def invalidate_cache(self, symbol: str | None = None) -> None:
        with self._lock:
            if symbol:
                symbol = symbol.upper()
                self._cache = {
                    key: value
                    for key, value in self._cache.items()
                    if key[0] != symbol
                }
            else:
                self._cache.clear()


_service: OptionsService | None = None
_service_lock = threading.Lock()


def get_options_service() -> OptionsService:
    global _service
    with _service_lock:
        if _service is None:
            _service = OptionsService()
    return _service
