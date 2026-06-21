"""
Session persistence — stores Zerodha enctokens in the journal DB.

Replaces the old .session.json file approach. Each session is keyed by
user_id so the table is ready for multi-user support when needed.
"""

from datetime import datetime, timezone
from src.journal.db import _get_connection


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def save(user_id: str, enctoken: str | None) -> None:
    """Upsert an active session for user_id. No-op if enctoken is None."""
    if not enctoken:
        return
    conn = _get_connection()
    now = _now()
    # Deactivate any existing sessions for this user, then insert fresh
    conn.execute(
        "UPDATE sessions SET is_active = 0 WHERE user_id = ?",
        (user_id,),
    )
    conn.execute(
        "INSERT INTO sessions (user_id, enctoken, created_at, last_used, is_active) VALUES (?, ?, ?, ?, 1)",
        (user_id, enctoken, now, now),
    )
    conn.commit()


def load(user_id: str | None = None) -> str | None:
    """
    Return the enctoken for the most recent active session.
    If user_id is given, scoped to that user; otherwise returns any active session
    (single-user convenience for startup).
    """
    conn = _get_connection()
    if user_id:
        row = conn.execute(
            "SELECT enctoken FROM sessions WHERE user_id = ? AND is_active = 1 ORDER BY last_used DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT enctoken FROM sessions WHERE is_active = 1 ORDER BY last_used DESC LIMIT 1",
        ).fetchone()
    if row is None:
        return None
    return row["enctoken"] if isinstance(row, dict) else row[0]


def delete(user_id: str) -> bool:
    """Deactivate all sessions for user_id. Returns True if any were active."""
    conn = _get_connection()
    conn.execute(
        "UPDATE sessions SET is_active = 0 WHERE user_id = ? AND is_active = 1",
        (user_id,),
    )
    conn.commit()
    return True


def list_active() -> list[dict]:
    """Return all active sessions (user_id + last_used). Does not return tokens."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT user_id, created_at, last_used FROM sessions WHERE is_active = 1 ORDER BY last_used DESC",
    ).fetchall()
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return [{"user_id": r["user_id"], "created_at": r["created_at"], "last_used": r["last_used"]} for r in rows]
    return [{"user_id": r[0], "created_at": r[1], "last_used": r[2]} for r in rows]
