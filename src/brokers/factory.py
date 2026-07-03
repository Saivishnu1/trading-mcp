"""
Broker factory — creates adapter instances and queries availability.
"""
from __future__ import annotations

import asyncio

from .base import BrokerAdapter
from .indmoney import INDmoneyBroker
from .zerodha import ZerodhaBroker


def get_broker_adapter(broker: str) -> BrokerAdapter:
    """Return a broker adapter by name.

    Args:
        broker: 'zerodha' | 'indmoney'

    Raises:
        ValueError: if broker name is not recognised.
    """
    if broker == "zerodha":
        return ZerodhaBroker()
    if broker == "indmoney":
        return INDmoneyBroker()
    raise ValueError(f"Unknown broker: {broker}")


async def get_available_brokers() -> list[BrokerAdapter]:
    """Return adapters whose is_authenticated() resolves to True."""
    brokers: list[BrokerAdapter] = [ZerodhaBroker(), INDmoneyBroker()]
    results = await asyncio.gather(
        *[b.is_authenticated() for b in brokers],
        return_exceptions=True,
    )
    return [b for b, ok in zip(brokers, results) if ok is True]


async def get_broker_status() -> dict:
    """Return authentication status for each supported broker."""
    zerodha = ZerodhaBroker()
    indmoney = INDmoneyBroker()
    z_auth, i_auth = await asyncio.gather(
        zerodha.is_authenticated(),
        indmoney.is_authenticated(),
        return_exceptions=True,
    )
    return {
        "zerodha": {
            "authenticated": bool(z_auth) if not isinstance(z_auth, Exception) else False,
        },
        "indmoney": {
            "authenticated": bool(i_auth) if not isinstance(i_auth, Exception) else False,
        },
    }
