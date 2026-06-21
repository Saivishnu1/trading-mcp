"""
Broker factory.

BROKER_BACKEND env var selects the implementation:
  zerodha_web  (default) — direct httpx calls to kite.zerodha.com
  jugaad       — jugaad-trader fallback

Multi-user: get_broker() reads current_user ContextVar set by request middleware.
Single-user / unauthenticated: falls back to the global default broker.
"""

import os
import threading
from contextvars import ContextVar

from src.broker.base import BrokerClient
from src.broker.zerodha_web import ZerodhaWebClient
from src.broker.jugaad import JugaadClient

# Set by request middleware to the resolved user_id for this async task
current_user: ContextVar[str | None] = ContextVar("current_user", default=None)

_default_broker: BrokerClient | None = None
_brokers: dict[str, BrokerClient] = {}  # user_id → broker
_lock = threading.Lock()


def _make_broker() -> BrokerClient:
    backend = os.environ.get("BROKER_BACKEND", "zerodha_web").lower()
    return JugaadClient() if backend == "jugaad" else ZerodhaWebClient()


def get_broker(user_id: str | None = None) -> BrokerClient:
    """Return the broker for the given user, or the current request's user, or the default."""
    uid = user_id or current_user.get()
    if uid:
        with _lock:
            if uid not in _brokers:
                broker = _make_broker()
                # Eagerly load their persisted session
                import src.session_store as session_store
                token = session_store.load(uid)
                if token:
                    broker.set_enctoken(token)
                _brokers[uid] = broker
        return _brokers[uid]

    # Single-user fallback
    global _default_broker
    with _lock:
        if _default_broker is None:
            _default_broker = _make_broker()
    return _default_broker


def reset_broker(user_id: str | None = None) -> None:
    """Remove a user's broker (or the default). Used by tests and logout."""
    global _default_broker
    with _lock:
        if user_id:
            _brokers.pop(user_id, None)
        else:
            _default_broker = None
            _brokers.clear()
