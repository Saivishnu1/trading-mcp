from typing import Protocol, runtime_checkable


@runtime_checkable
class BrokerClient(Protocol):
    """
    Structural interface every broker backend must satisfy.
    MCP tools depend only on this — never on a concrete implementation.
    """

    def login(self, user_id: str, password: str, totp: str) -> dict:
        """Authenticate and return user info dict."""
        ...

    def profile(self) -> dict:
        """Return the authenticated user's profile."""
        ...

    def holdings(self) -> list[dict]:
        """Return long-term demat holdings."""
        ...

    def positions(self) -> dict:
        """Return intraday/net positions as {'net': [...], 'day': [...]}."""
        ...

    def margins(self, segment: str = "equity") -> dict:
        """Return fund margins for equity or commodity segment."""
        ...

    def is_authenticated(self) -> bool:
        """True if a valid session is active."""
        ...

    def save_session(self, path: str) -> None:
        """Persist auth session to a JSON file."""
        ...

    def load_session(self, path: str) -> bool:
        """Restore auth session from a JSON file. Returns True on success."""
        ...
