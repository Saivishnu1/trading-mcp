"""Order execution layer — places orders via a broker adapter and logs them.

Exposes ``submit_order`` (the single entry point used by the Telegram bot and
the web app) so order-placement logic lives in exactly one place.
"""
from .service import submit_order

__all__ = ["submit_order"]
