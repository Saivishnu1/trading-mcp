"""International benchmark price sources for MCX divergence checks.

Ported directly from the OilPriceAPI REST contract (MIT-licensed reference
implementation: github.com/OilpriceAPI/mcp-server) as plain Python — not run
as a separate MCP server process, since this repo is a single FastMCP server.

Covers WTI crude and Henry Hub natural gas only — the two commodities this
codebase has a real benchmark source for. No MCX/Indian-exchange data exists
here or anywhere free (see docs/research/mcx_scope_20260711.md) — this module
is exclusively the international side of a divergence comparison.

OILPRICEAPI_KEY is optional: oilpriceapi.com offers a limited keyless demo
mode, so a missing key degrades to that rather than failing outright.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.oilpriceapi.com/v1"
_TOKEN_ENV = "OILPRICEAPI_KEY"

# Commodity code -> OilPriceAPI's by_code identifier.
COMMODITY_CODES: dict[str, str] = {
    "CRUDEOIL": "WTI_USD",
    "CRUDEOILM": "WTI_USD",
    "NATURALGAS": "NATURAL_GAS_USD",
    "NATGASMINI": "NATURAL_GAS_USD",
}


def _headers() -> dict:
    token = os.environ.get(_TOKEN_ENV, "").strip()
    return {"Authorization": f"Token {token}"} if token else {}


def _get_client():
    """Patchable factory — tests replace this instead of hitting the network."""
    return httpx.Client(base_url=_BASE, timeout=10.0)


def fetch_latest_price(commodity_code: str) -> float | None:
    """Latest price for an OilPriceAPI commodity code, or None on any failure."""
    try:
        with _get_client() as client:
            r = client.get("/prices/latest", params={"by_code": commodity_code}, headers=_headers())
            r.raise_for_status()
            body = r.json()
            if body.get("status") != "success":
                return None
            return float(body["data"]["price"])
    except Exception as exc:
        logger.debug("OilPriceAPI fetch_latest_price failed for %s: %s", commodity_code, exc)
        return None


def fetch_prior_day_price(commodity_code: str) -> float | None:
    """Approximate previous-day price via the past_day series (first point),
    used to compute the benchmark's own % change. Returns None on failure."""
    try:
        with _get_client() as client:
            r = client.get("/prices/past_day", params={"by_code": commodity_code}, headers=_headers())
            r.raise_for_status()
            body = r.json()
            if body.get("status") != "success":
                return None
            series = body.get("data") or []
            if not series:
                return None
            first = series[0]
            price = first.get("price") if isinstance(first, dict) else first
            if price is None:
                return None
            return float(price)
    except Exception as exc:
        logger.debug("OilPriceAPI fetch_prior_day_price failed for %s: %s", commodity_code, exc)
        return None


def fetch_benchmark_change_pct(commodity_code: str) -> float | None:
    """Benchmark's own % change (latest vs. prior day), or None if either
    fetch fails — callers must treat None as 'benchmark unavailable', not 0."""
    latest = fetch_latest_price(commodity_code)
    prior = fetch_prior_day_price(commodity_code)
    if latest is None or prior is None or prior == 0:
        return None
    return round((latest - prior) / prior * 100, 4)
