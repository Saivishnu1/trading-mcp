"""
Broker factory.

BROKER_BACKEND env var selects the implementation:
  zerodha_web  (default) — direct httpx calls to kite.zerodha.com
  jugaad       — jugaad-trader fallback
"""

import os
import threading

from src.broker.base import BrokerClient
from src.broker.zerodha_web import ZerodhaWebClient
from src.broker.jugaad import JugaadClient

_client: BrokerClient | None = None
_lock = threading.Lock()


def get_broker() -> BrokerClient:
    global _client
    with _lock:
        if _client is None:
            backend = os.environ.get("BROKER_BACKEND", "zerodha_web").lower()
            if backend == "jugaad":
                _client = JugaadClient()
            else:
                _client = ZerodhaWebClient()
    return _client


def reset_broker() -> None:
    """Replace the singleton (used by tests or after a backend switch)."""
    global _client
    with _lock:
        _client = None
