"""
API key store — maps opaque session tokens to user_ids.

Keys are generated at login and stored in the api_keys table (schema v6).
The MCP client sends the key in the Authorization header; middleware resolves
it to a user_id without the agent ever seeing the key.
"""

import secrets
from datetime import UTC, datetime

from src.journal.db import _get_connection


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def generate() -> str:
    """Generate a new opaque API key."""
    return "sess_" + secrets.token_hex(24)


def get_or_create(user_id: str) -> tuple[str, bool]:
    """
    Return (api_key, is_new) for a user.
    If an active key already exists, return it unchanged — API keys survive re-logins.
    Only creates a new key on first login or after explicit rotation/logout.
    """
    conn = _get_connection()
    row = conn.execute(
        "SELECT api_key FROM api_keys WHERE user_id = ? AND is_active = 1 ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if row:
        existing = row["api_key"] if isinstance(row, dict) else row[0]
        return existing, False
    # No active key — generate one
    api_key = generate()
    conn.execute(
        "INSERT INTO api_keys (api_key, user_id, created_at, is_active) VALUES (?, ?, ?, 1)",
        (api_key, user_id, _now()),
    )
    conn.commit()
    return api_key, True


def save(api_key: str, user_id: str) -> None:
    """Force-insert a new API key, deactivating previous ones. Use for explicit rotation."""
    conn = _get_connection()
    conn.execute(
        "UPDATE api_keys SET is_active = 0 WHERE user_id = ?",
        (user_id,),
    )
    conn.execute(
        "INSERT INTO api_keys (api_key, user_id, created_at, is_active) VALUES (?, ?, ?, 1)",
        (api_key, user_id, _now()),
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
