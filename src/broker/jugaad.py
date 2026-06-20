"""
Fallback broker: wraps jugaad-trader's Zerodha class.

jugaad-trader automates the same Kite web login flow as ZerodhaWebClient
but is maintained as a third-party library. Use this when the primary
client's direct httpx implementation breaks due to Zerodha API changes.

Switch via: BROKER_BACKEND=jugaad in .env
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class JugaadClient:
    """Fallback broker that delegates to jugaad-trader's Zerodha class."""

    def __init__(self) -> None:
        self._kite = None  # jugaad_trader.Zerodha, imported lazily

    def _import_zerodha(self):
        try:
            from jugaad_trader import Zerodha  # type: ignore[import]
            return Zerodha
        except ImportError as exc:
            raise ImportError(
                "jugaad-trader is not installed. "
                "Run: uv add jugaad-trader"
            ) from exc

    def _require_auth(self):
        if self._kite is None:
            raise RuntimeError("Not authenticated. Call zerodha_login() first.")
        return self._kite

    # ------------------------------------------------------------------
    # BrokerClient interface
    # ------------------------------------------------------------------

    def login(self, user_id: str, password: str, totp: str) -> dict:
        Zerodha = self._import_zerodha()
        kite = Zerodha(user_id=user_id, password=password, twofa=totp)
        kite.login()
        self._kite = kite
        logger.info("JugaadClient: login successful for %s", user_id)
        try:
            return kite.profile()
        except Exception:
            return {"user_id": user_id}

    def profile(self) -> dict:
        return self._require_auth().profile()

    def holdings(self) -> list[dict]:
        return self._require_auth().holdings()

    def positions(self) -> dict:
        return self._require_auth().positions()

    def margins(self, segment: str = "equity") -> dict:
        return self._require_auth().margins(segment=segment)

    def is_authenticated(self) -> bool:
        if self._kite is None:
            return False
        try:
            self._kite.profile()
            return True
        except Exception:
            return False

    def save_session(self, path: str) -> None:
        if self._kite is None:
            return
        data: dict = {}
        # jugaad-trader exposes enctoken after a successful login
        for attr in ("enctoken", "access_token"):
            val = getattr(self._kite, attr, None)
            if val:
                data[attr] = val
                break
        if data:
            Path(path).write_text(json.dumps(data))

    def load_session(self, path: str) -> bool:
        p = Path(path)
        if not p.exists():
            return False
        try:
            data = json.loads(p.read_text())
            token = data.get("enctoken") or data.get("access_token")
            if not token:
                return False
            Zerodha = self._import_zerodha()
            kite = Zerodha()
            # Setting enctoken directly is sufficient for jugaad-trader to
            # authenticate subsequent requests without needing set_access_token().
            kite.enctoken = token
            self._kite = kite
            logger.info("JugaadClient: session restored from %s", path)
            return True
        except Exception as exc:
            logger.warning("JugaadClient: could not load session: %s", exc)
            return False

    def orders(self) -> list[dict]:
        return self._require_auth().orders()

    def trades(self) -> list[dict]:
        return self._require_auth().trades()

