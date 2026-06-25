"""
BSE index option chain fetcher.

Supports only the live BSE index option-chain endpoints needed for:
  - SENSEX
  - BANKEX

Responses are normalised into the same internal schema used by the NSE
options service so the tool layer can stay exchange-agnostic.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

_BSE_API_BASE = "https://api.bseindia.com/BseIndiaAPI/api"
_BSE_REFERER = "https://www.bseindia.com/markets/derivatives/deriReports/optionchain.aspx"
_CACHE_TTL = 60  # seconds
_RETRIES = 2
_SUPPORTED = {"SENSEX", "BANKEX"}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": _BSE_REFERER,
    "X-Requested-With": "XMLHttpRequest",
}


@dataclass(slots=True)
class BSEOptionsError(RuntimeError):
    code: str
    message: str
    details: dict[str, Any]

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, f"{self.code}: {self.message}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    return None if number is None else int(number)


def _compact_leg(data: dict[str, Any]) -> dict[str, Any] | None:
    return data if any(value is not None for value in data.values()) else None


class BSEOptionsService:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._session.headers.update(_HEADERS)
        self._cache: dict[tuple[str, Optional[str]], tuple[dict, float]] = {}
        self._expiries_cache: dict[str, tuple[list[str], float]] = {}
        self._underlyings_cache: tuple[dict[str, str], float] | None = None
        self._lock = threading.Lock()

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        raw = symbol.strip().upper()
        if ":" in raw:
            raw = raw.split(":", 1)[1]
        return raw.removesuffix(".NS").removesuffix(".BO")

    def _request_json(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{_BSE_API_BASE}{path}"
        last_error: Exception | None = None

        for attempt in range(_RETRIES):
            try:
                response = self._session.get(url, params=params, timeout=20)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise BSEOptionsError(
                        "BSE_MALFORMED_PAYLOAD",
                        "BSE API returned a non-object payload.",
                        {"path": path, "params": params, "payload_type": type(payload).__name__},
                    )
                return payload
            except BSEOptionsError:
                raise
            except requests.HTTPError as exc:
                status_code = getattr(exc.response, "status_code", None)
                raise BSEOptionsError(
                    "BSE_HTTP_ERROR",
                    "BSE API request failed.",
                    {"path": path, "params": params, "status_code": status_code},
                ) from exc
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt == _RETRIES - 1:
                    break

        raise BSEOptionsError(
            "BSE_REQUEST_FAILED",
            "Could not complete BSE API request.",
            {
                "path": path,
                "params": params,
                "error": str(last_error) if last_error else "unknown",
            },
        ) from last_error

    def _load_underlyings(self) -> dict[str, str]:
        with self._lock:
            cached = self._underlyings_cache
            if cached and (time.monotonic() - cached[1]) < _CACHE_TTL:
                return cached[0]

        payload = self._request_json(
            "/ddlUnderlyingAsset/w",
            params={"ProductType": "IO", "scrip_cd": "0"},
        )
        rows = payload.get("Table")
        if not isinstance(rows, list) or not rows:
            raise BSEOptionsError(
                "BSE_EMPTY_UNDERLYINGS",
                "BSE underlying-asset list was empty.",
                {"payload_keys": sorted(payload.keys())},
            )

        mapping: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("UlaCODE", "")).strip().upper()
            code = row.get("scrip_cd")
            if name and code not in (None, ""):
                mapping[name] = str(code)

        missing = sorted(_SUPPORTED - set(mapping))
        if missing:
            raise BSEOptionsError(
                "BSE_UNDERLYING_NOT_FOUND",
                "Required BSE index underlyings were not present in the official dropdown.",
                {"missing": missing, "available": sorted(mapping)},
            )

        with self._lock:
            self._underlyings_cache = (mapping, time.monotonic())
        return mapping

    def _resolve_scrip_code(self, symbol: str) -> str:
        normalized = self._normalize_symbol(symbol)
        if normalized not in _SUPPORTED:
            raise BSEOptionsError(
                "BSE_SYMBOL_UNSUPPORTED",
                "Only SENSEX and BANKEX are supported by the BSE options service.",
                {"symbol": symbol, "normalized": normalized, "supported": sorted(_SUPPORTED)},
            )
        return self._load_underlyings()[normalized]

    def _fetch_expiries(self, symbol: str, scrip_code: str) -> list[str]:
        normalized = self._normalize_symbol(symbol)
        with self._lock:
            cached = self._expiries_cache.get(normalized)
            if cached and (time.monotonic() - cached[1]) < _CACHE_TTL:
                return cached[0]

        payload = self._request_json(
            "/ddlExpiry_IV/w",
            params={"ProductType": "IO", "scrip_cd": scrip_code},
        )
        rows = payload.get("Table1")
        if not isinstance(rows, list):
            raise BSEOptionsError(
                "BSE_MALFORMED_PAYLOAD",
                "BSE expiry payload did not contain Table1 list.",
                {"symbol": normalized, "payload_keys": sorted(payload.keys())},
            )

        expiries = [str(row.get("ExpiryDate", "")).strip() for row in rows if str(row.get("ExpiryDate", "")).strip()]
        if not expiries:
            raise BSEOptionsError(
                "BSE_EMPTY_EXPIRIES",
                "BSE returned no expiries for the requested index.",
                {"symbol": normalized, "scrip_code": scrip_code},
            )

        with self._lock:
            self._expiries_cache[normalized] = (expiries, time.monotonic())
        return expiries

    @staticmethod
    def _normalize_row(row: dict[str, Any], expiry: str) -> dict[str, Any]:
        strike = _to_float(row.get("Strike_Price1") or row.get("Strike_Price"))
        call_leg = _compact_leg({
            "openInterest": _to_int(row.get("C_Open_Interest")),
            "changeinOpenInterest": _to_int(row.get("C_Absolute_Change_OI")),
            "totalTradedVolume": _to_int(row.get("C_Vol_Traded")),
            "impliedVolatility": _to_float(row.get("C_IV")),
            "lastPrice": _to_float(row.get("C_Last_Trd_Price")),
            "bidprice": _to_float(row.get("C_BidPrice")),
            "askPrice": _to_float(row.get("C_OfferPrice")),
        })
        put_leg = _compact_leg({
            "openInterest": _to_int(row.get("Open_Interest")),
            "changeinOpenInterest": _to_int(row.get("Absolute_Change_OI")),
            "totalTradedVolume": _to_int(row.get("Vol_Traded")),
            "impliedVolatility": _to_float(row.get("IV")),
            "lastPrice": _to_float(row.get("Last_Trd_Price")),
            "bidprice": _to_float(row.get("BidPrice")),
            "askPrice": _to_float(row.get("OfferPrice")),
        })
        return {
            "strikePrice": strike,
            "expiryDate": expiry,
            "CE": call_leg,
            "PE": put_leg,
        }

    def _normalize_chain(self, symbol: str, expiry: str, payload: dict[str, Any]) -> dict[str, Any]:
        rows = payload.get("Table")
        if not isinstance(rows, list):
            raise BSEOptionsError(
                "BSE_MALFORMED_PAYLOAD",
                "BSE option-chain payload did not contain Table list.",
                {"symbol": symbol, "expiry": expiry, "payload_keys": sorted(payload.keys())},
            )
        if not rows:
            raise BSEOptionsError(
                "BSE_EMPTY_CHAIN",
                "BSE option-chain payload contained no strike rows.",
                {"symbol": symbol, "expiry": expiry},
            )

        normalized_rows = [self._normalize_row(row, expiry) for row in rows if isinstance(row, dict)]
        normalized_rows = [row for row in normalized_rows if row.get("strikePrice") is not None]
        if not normalized_rows:
            raise BSEOptionsError(
                "BSE_EMPTY_CHAIN",
                "BSE option-chain payload contained no normalizable strike rows.",
                {"symbol": symbol, "expiry": expiry},
            )

        spot = _to_float(rows[0].get("UlaValue")) if isinstance(rows[0], dict) else None
        return {
            "records": {
                "data": normalized_rows,
                "expiryDates": self.available_expiries(symbol),
                "underlyingValue": spot,
            },
            "source_meta": {
                "exchange": "BSE",
                "symbol": self._normalize_symbol(symbol),
                "as_of": (payload.get("ASON") or {}).get("DT_TM"),
            },
        }

    def get_option_chain(self, symbol: str, expiry: Optional[str] = None) -> dict:
        normalized = self._normalize_symbol(symbol)
        scrip_code = self._resolve_scrip_code(normalized)
        available = self._fetch_expiries(normalized, scrip_code)
        resolved = expiry if expiry in available else available[0]
        cache_key = (normalized, resolved)

        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and (time.monotonic() - cached[1]) < _CACHE_TTL:
                return cached[0]

        payload = self._request_json(
            "/DerivOptionChain_IV/w",
            params={"Expiry": resolved, "scrip_cd": scrip_code, "strprice": "0"},
        )
        chain = self._normalize_chain(normalized, resolved, payload)

        with self._lock:
            self._cache[cache_key] = (chain, time.monotonic())
        return chain

    def available_expiries(self, symbol: str) -> list[str]:
        normalized = self._normalize_symbol(symbol)
        scrip_code = self._resolve_scrip_code(normalized)
        return self._fetch_expiries(normalized, scrip_code)

    def invalidate_cache(self, symbol: str | None = None) -> None:
        with self._lock:
            if symbol:
                normalized = self._normalize_symbol(symbol)
                self._cache = {
                    key: value
                    for key, value in self._cache.items()
                    if key[0] != normalized
                }
                self._expiries_cache.pop(normalized, None)
            else:
                self._cache.clear()
                self._expiries_cache.clear()
                self._underlyings_cache = None


_service: BSEOptionsService | None = None
_service_lock = threading.Lock()


def get_bse_options_service() -> BSEOptionsService:
    global _service
    with _service_lock:
        if _service is None:
            _service = BSEOptionsService()
    return _service
