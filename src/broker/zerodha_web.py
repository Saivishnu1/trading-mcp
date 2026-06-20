"""
Primary broker: talks directly to Zerodha's internal Kite web API using httpx.

No Kite Connect subscription required — uses the same endpoints as the Kite
web app (kite.zerodha.com). Auth produces an `enctoken` cookie/header that
grants access to portfolio and account APIs for a personal account.
"""

import json
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://kite.zerodha.com"
_HEADERS = {
    "X-Kite-Version": "3",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://kite.zerodha.com/",
    "Origin": "https://kite.zerodha.com",
    "Accept": "application/json, text/plain, */*",
}


class ZerodhaWebClient:
    """
    Broker client backed by Zerodha's Kite web API (free, personal account).

    Login produces an `enctoken` that is sent as `Authorization: enctoken <token>`
    on all subsequent requests. This is identical to what the Kite web app does.
    """

    def __init__(self) -> None:
        self._enctoken: str | None = None
        self._http = httpx.Client(
            base_url=_BASE,
            headers=_HEADERS,
            follow_redirects=True,
            timeout=15.0,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_token(self, token: str) -> None:
        self._enctoken = token
        self._http.headers["Authorization"] = f"enctoken {token}"
        # Set the enctoken cookie explicitly so both auth mechanisms are active,
        # matching what a real Kite browser session does.
        self._http.cookies.set("enctoken", token, domain="kite.zerodha.com")

    def _require_auth(self) -> None:
        if not self._enctoken:
            raise RuntimeError(
                "Not authenticated. Call zerodha_login() first."
            )

    def _get(self, path: str) -> object:
        self._require_auth()
        r = self._http.get(path)
        r.raise_for_status()
        body = r.json()
        if body.get("status") == "error":
            raise RuntimeError(
                f"Zerodha API error: {body.get('message', 'unknown error')}"
            )
        data = body["data"]
        # Zerodha occasionally returns a plain string in "data" with status "success"
        # for restricted endpoints (e.g. "not available in frontend proxy mode").
        # Catching it here prevents a pydantic type-mismatch from crashing the server.
        if isinstance(data, str):
            raise RuntimeError(f"Zerodha API error: {data}")
        return data

    # ------------------------------------------------------------------
    # BrokerClient interface
    # ------------------------------------------------------------------

    def login(self, user_id: str, password: str, totp: str) -> dict:
        # Step 1 — password auth
        r = self._http.post(
            "/api/login",
            data={"user_id": user_id, "password": password},
        )
        r.raise_for_status()
        body = r.json()
        if body.get("status") == "error":
            raise RuntimeError(f"Login failed: {body.get('message')}")

        request_id: str = body["data"]["request_id"]

        # Step 2 — TOTP verification
        r = self._http.post(
            "/api/twofa",
            data={
                "user_id": user_id,
                "request_id": request_id,
                "twofa_value": totp,
                "twofa_type": "totp",
                "skip_session": "",
            },
        )
        r.raise_for_status()
        body = r.json()
        if body.get("status") == "error":
            raise RuntimeError(f"TOTP failed: {body.get('message')}")

        # enctoken arrives as a Set-Cookie header
        token = r.cookies.get("enctoken") or body.get("data", {}).get("enctoken")
        if not token:
            raise RuntimeError(
                "Zerodha did not return an enctoken — check credentials or TOTP."
            )

        self._set_token(token)
        logger.info("ZerodhaWebClient: login successful for %s", user_id)
        return body.get("data", {})

    def profile(self) -> dict:
        return self._get("/api/user/profile")  # type: ignore[return-value]

    def holdings(self) -> list[dict]:
        return self._get("/api/portfolio/holdings")  # type: ignore[return-value]

    def positions(self) -> dict:
        return self._get("/api/portfolio/positions")  # type: ignore[return-value]

    def margins(self, segment: str = "equity") -> dict:
        return self._get(f"/api/user/margins/{segment}")  # type: ignore[return-value]

    def orders(self) -> list[dict]:
        return self._get("/api/orders")  # type: ignore[return-value]

    def trades(self) -> list[dict]:
        return self._get("/api/trades")  # type: ignore[return-value]

    def is_authenticated(self) -> bool:
        if not self._enctoken:
            return False
        try:
            self.profile()
            return True
        except Exception:
            return False

    def save_session(self, path: str) -> None:
        if not self._enctoken:
            return
        Path(path).write_text(json.dumps({"enctoken": self._enctoken}))

    def load_session(self, path: str) -> bool:
        p = Path(path)
        if not p.exists():
            return False
        try:
            data = json.loads(p.read_text())
            token = data.get("enctoken", "").strip()
            if not token:
                return False
            self._set_token(token)
            logger.info("ZerodhaWebClient: session restored from %s", path)
            return True
        except Exception as exc:
            logger.warning("ZerodhaWebClient: could not load session: %s", exc)
            return False
