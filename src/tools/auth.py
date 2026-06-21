import os
import logging
from mcp.server.fastmcp import FastMCP
from src.broker import get_broker

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def zerodha_login() -> dict:
        """Check authentication status and return a browser login URL if not authenticated.

        Credentials are NEVER passed through this tool — they are entered directly
        in the browser so they never appear in agent context, tool logs, or MCP traffic.

        If already authenticated, returns immediately without requiring a login.

        Returns:
            authenticated=True  — session is active, no action needed.
            authenticated=False — open login_url in your browser to log in securely.
        """
        broker = get_broker()
        if broker.is_authenticated():
            return {"authenticated": True, "message": "Already authenticated."}

        # PUBLIC_URL must be set to your Railway/remote URL in production.
        # Falls back to localhost for local development.
        base_url = os.environ.get("PUBLIC_URL", "http://localhost:8000").rstrip("/")
        return {
            "authenticated": False,
            "login_url": f"{base_url}/login",
            "message": (
                f"Open this URL in your browser to log in securely: {base_url}/login\n"
                "Credentials are entered directly into the server — they never pass through the agent."
            ),
        }

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
