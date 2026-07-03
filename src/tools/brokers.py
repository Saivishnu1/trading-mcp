"""
Phase 1 — Broker Intelligence tools.

Six new MCP tools for unified multi-broker portfolio access:
  get_unified_holdings, get_unified_positions, get_unified_funds,
  get_unified_orders, get_broker_status, get_indmoney_greeks.
"""
from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP

from src import meta as _meta
from src.brokers.factory import (
    get_broker_adapter,
    get_broker_status as _get_broker_status,
)
from src.brokers.indmoney import INDmoneyBroker
from src.brokers.zerodha import ZerodhaBroker


def _broker_meta() -> dict:
    return _meta.build_meta(
        type_=_meta.TYPE_FACT,
        validation_status=_meta.VALIDATION_VERIFIED,
        data_quality=_meta.DQ_VALID,
        source="broker_api",
        account_type="LIVE_ACCOUNT",
    )


async def _fetch_broker_data(adapter, method_name: str) -> dict:
    """Call adapter.<method_name>() and return a broker result envelope."""
    try:
        method = getattr(adapter, method_name)
        items = await method()
        return {
            "data": [i.to_dict() for i in items],
            "status": "ok",
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


async def _unified(method_name: str, broker: str) -> dict:
    """Core helper for all unified tools."""
    brokers_result: dict = {}
    combined: list = []

    if broker in ("zerodha", "all"):
        z = ZerodhaBroker()
        try:
            auth = await z.is_authenticated()
        except Exception:
            auth = False
        if auth:
            brokers_result["zerodha"] = await _fetch_broker_data(z, method_name)
            if brokers_result["zerodha"]["status"] == "ok":
                combined.extend(brokers_result["zerodha"]["data"])
        else:
            brokers_result["zerodha"] = {"status": "unauthenticated"}

    if broker in ("indmoney", "all"):
        ind = INDmoneyBroker()
        try:
            auth = await ind.is_authenticated()
        except Exception:
            auth = False
        if auth:
            brokers_result["indmoney"] = await _fetch_broker_data(ind, method_name)
            if brokers_result["indmoney"]["status"] == "ok":
                combined.extend(brokers_result["indmoney"]["data"])
        else:
            # Distinguish "token not set" from "token set but invalid"
            from src.brokers.indmoney import _TOKEN_ENV
            import os
            if not os.environ.get(_TOKEN_ENV, ""):
                brokers_result["indmoney"] = {"status": "not_configured"}
            else:
                brokers_result["indmoney"] = {"status": "unauthenticated"}

    payload = {
        "brokers": brokers_result,
        "combined": combined,
        "total": len(combined),
    }
    m = _broker_meta()
    return _meta.wrap(payload, m)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def get_unified_holdings(broker: str = "all") -> dict:
        """Returns demat holdings from zerodha, indmoney, or both brokers combined.

        Args:
            broker: "zerodha" | "indmoney" | "all" (default "all")

        Returns a unified response with per-broker status and a combined list.
        """
        return await _unified("get_holdings", broker)

    @mcp.tool()
    async def get_unified_positions(broker: str = "all") -> dict:
        """Returns open positions from zerodha, indmoney, or both brokers combined.

        Args:
            broker: "zerodha" | "indmoney" | "all" (default "all")

        Returns a unified response with per-broker status and a combined list.
        """
        return await _unified("get_positions", broker)

    @mcp.tool()
    async def get_unified_funds(broker: str = "all") -> dict:
        """Returns available funds from zerodha, indmoney, or both brokers combined.

        Args:
            broker: "zerodha" | "indmoney" | "all" (default "all")

        Returns a unified response with per-broker status and a combined list.
        """
        return await _unified("get_funds", broker)

    @mcp.tool()
    async def get_unified_orders(broker: str = "all") -> dict:
        """Returns today's orders from zerodha, indmoney, or both brokers combined.

        Args:
            broker: "zerodha" | "indmoney" | "all" (default "all")

        Returns a unified response with per-broker status and a combined list.
        """
        return await _unified("get_orders", broker)

    @mcp.tool()
    async def get_broker_status() -> dict:
        """Returns authentication status for each configured broker (zerodha, indmoney)."""
        status = await _get_broker_status()
        m = _broker_meta()
        return _meta.wrap(status, m)

    @mcp.tool()
    async def get_indmoney_greeks(tokens: list[str]) -> dict:
        """Returns option Greeks (IV, Delta, Gamma, Theta, Vega) via INDmoney API.

        Args:
            tokens: list of instrument tokens e.g. ["BANKNIFTY28MAR24C45100"]

        Note: Coming soon in INDstocks API — currently returns not_available.
        """
        broker = INDmoneyBroker()
        result = await broker.get_greeks(tokens)
        m = _broker_meta()
        return _meta.wrap(result, m)
