import logging
import os

from mcp.server.fastmcp import FastMCP

import src.api_key_store as api_key_store
import src.session_store as session_store
from src.broker import current_user, get_broker, require_broker, reset_broker

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def zerodha_login() -> dict:
        """Check authentication status and return a browser login URL if not authenticated.

        Credentials are NEVER passed through this tool — they are entered directly
        in the browser so they never appear in agent context, tool logs, or MCP traffic.

        If already authenticated (valid API key in request), returns immediately.
        Otherwise returns a login URL — open it in your browser to authenticate.

        Returns:
            authenticated=True  — this client has a valid session, no action needed.
            authenticated=False — open login_url in your browser to log in securely.
        """
        uid = current_user.get()
        railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
        default_url = f"https://{railway_domain}" if railway_domain else "http://localhost:8000"
        base_url = os.environ.get("PUBLIC_URL", default_url).rstrip("/")

        if uid and uid != "__guest__" and get_broker(uid).is_authenticated():
            return {"authenticated": True, "message": "Already authenticated."}

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
        return require_broker().profile()

    @mcp.tool()
    def check_auth_status() -> dict:
        """Check whether this client has an active Zerodha session.

        Returns authenticated=True only if the request carries a valid API key
        and the associated session is active.
        """
        uid = current_user.get()
        if not uid or uid == "__guest__":
            return {"authenticated": False, "backend": None}
        broker = get_broker(uid)
        return {
            "authenticated": broker.is_authenticated(),
            "backend": type(broker).__name__,
        }

    @mcp.tool()
    def zerodha_logout() -> dict:
        """Log out the current user — clears their session and invalidates the API key.

        User is identified automatically from the request's API key. No parameters needed.
        """
        uid = current_user.get() or session_store.get_active_user_id()
        if not uid:
            return {"logged_out": False, "error": "No active session found."}
        session_store.delete(uid)
        api_key_store.delete(uid)
        reset_broker(uid)
        get_broker().clear_enctoken()
        logger.info("MCP logout: %s", uid)
        return {"logged_out": True, "user_id": uid}
