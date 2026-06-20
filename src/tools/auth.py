import os
import logging
import pyotp
from mcp.server.fastmcp import FastMCP
from src.broker import get_broker

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def zerodha_login(
        user_id: str,
        password: str,
        totp_code: str | None = None,
        totp_secret: str | None = None,
    ) -> dict:
        """Log in to your personal Zerodha account.

        No Kite Connect API subscription required — uses the same web login
        as the Kite browser app.

        Provide either:
          totp_code   — the 6-digit code from your authenticator app right now, OR
          totp_secret — the base32 TOTP secret (scanned from Zerodha's QR code);
                        the server generates the code automatically.

        The session is persisted to disk so subsequent server restarts do not
        require re-login until the token expires (~24 hours).

        Args:
            user_id: Your Zerodha client ID (e.g. 'ZK1234').
            password: Your Zerodha login password.
            totp_code: Current 6-digit TOTP (mutually exclusive with totp_secret).
            totp_secret: Base32 TOTP secret for automatic code generation.
        """
        if not totp_code and not totp_secret:
            raise ValueError("Provide either totp_code or totp_secret.")

        if not totp_code:
            totp_code = pyotp.TOTP(totp_secret).now()

        broker = get_broker()
        data = broker.login(user_id=user_id, password=password, totp=totp_code)

        session_file = os.environ.get("SESSION_FILE", ".session.json")
        broker.save_session(session_file)

        backend = type(broker).__name__
        return {"status": "authenticated", "backend": backend, **data}

    @mcp.tool()
    def get_profile() -> dict:
        """Return the authenticated Zerodha user's profile.

        Includes user_id, user_name, email, broker, and enabled exchanges.
        """
        return get_broker().profile()

    @mcp.tool()
    def check_auth_status() -> dict:
        """Check whether the server has an active Zerodha session.

        Returns the backend name and auth status without making a live
        profile API call.
        """
        broker = get_broker()
        return {
            "authenticated": broker.is_authenticated(),
            "backend": type(broker).__name__,
        }
