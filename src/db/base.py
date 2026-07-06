"""SQLAlchemy declarative base and shared column helpers.

All ORM models must inherit from Base. The schema they belong to is set
per-model via __table_args__ = {"schema": "<schema_name>"}.

Schemas on this PostgreSQL instance:
  zerodha   — core app tables (trades, sessions, api_keys)
  journal   — recommendation_log, decision quality tables
  audit     — immutable audit trail (append-only)
  auth      — OAuth tokens, PKCE state, client registrations
  migration — staging area for Railway data import
  monitor   — live position monitor (Phase 9A): users, positions, alerts
"""
from __future__ import annotations

try:
    from sqlalchemy import MetaData
    from sqlalchemy.orm import DeclarativeBase

    # Naming convention ensures Alembic can auto-generate constraint names
    # consistently across all schemas, which is required for reliable
    # downgrade migrations.
    _NAMING_CONVENTION = {
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }

    class Base(DeclarativeBase):
        metadata = MetaData(naming_convention=_NAMING_CONVENTION)

except ImportError:
    # Windows dev — SQLAlchemy not installed. Provide a stub so imports don't crash.
    class Base:  # type: ignore[no-redef]
        pass
