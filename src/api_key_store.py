"""
API key store — maps opaque session tokens to user_ids.

Keys are generated at login and stored in the api_keys table (schema v6).
The MCP client sends the key in the Authorization header; middleware resolves
it to a user_id without the agent ever seeing the key.
"""

import secrets
from datetime import datetime, timezone
from src.journal.db import _get_connection


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def generate() -> str:
    """Generate a new opaque API key."""
    return "sess_" + secrets.token_hex(24)


def save(api_key: str, user_id: str) -> None:
    """Store a new API key mapped to user_id. Deactivates previous keys for the user."""
    conn = _get_connection()
    now = _now()
    conn.execute(
        "UPDATE api_keys SET is_active = 0 WHERE user_id = ?",
        (user_id,),
    )
    conn.execute(
        "INSERT INTO api_keys (api_key, user_id, created_at, is_active) VALUES (?, ?, ?, 1)",
        (api_key, user_id, now),
    )
    conn.commit()


def lookup(api_key: str) -> str | None:
    """Resolve an API key to a user_id. Returns None if invalid or inactive."""
    if not api_key:
        return None
    conn = _get_connection()
    row = conn.execute(
        "SELECT user_id FROM api_keys WHERE api_key = ? AND is_active = 1",
        (api_key,),
    ).fetchone()
    if row is None:
        return None
    # Update last_used
    conn.execute(
        "UPDATE api_keys SET last_used = ? WHERE api_key = ?",
        (_now(), api_key),
    )
    conn.commit()
    return row["user_id"] if isinstance(row, dict) else row[0]


def delete(user_id: str) -> None:
    """Deactivate all API keys for a user (called on logout)."""
    conn = _get_connection()
    conn.execute(
        "UPDATE api_keys SET is_active = 0 WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()
