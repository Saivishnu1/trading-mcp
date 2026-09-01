import threading

from src.market.service import MarketService

_service: MarketService | None = None
_lock = threading.Lock()


def get_market() -> MarketService:
    global _service
    with _lock:
        if _service is None:
            _service = MarketService()
    return _service
