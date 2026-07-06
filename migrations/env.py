"""Alembic env.py — async migrations across multiple PostgreSQL schemas.

Schemas managed:
  zerodha   — trades
  journal   — recommendation_log
  auth      — sessions, api_keys
  audit     — (future append-only audit trail)
  migration — Turso data staging (empty in normal operation)

DATABASE_URL is read from the environment. On the Oracle VM it is loaded from
/etc/zerodha-mcp/.env by the systemd service before this process starts.
Never hardcode credentials here.

Migration locking: a PostgreSQL session-level advisory lock (id 987654321) is
acquired before any DDL runs and released when the connection closes. This
prevents two concurrent alembic upgrade head calls from racing each other.
"""
from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

# ---------------------------------------------------------------------------
# Make src/ importable from the repo root (set in alembic.ini prepend_sys_path)
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.base import Base
import src.db.models  # noqa: F401 — register all ORM models with Base.metadata

# ---------------------------------------------------------------------------
# Alembic Config
# ---------------------------------------------------------------------------
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# All managed schemas — Alembic will include/exclude tables by schema.
MANAGED_SCHEMAS = ["zerodha", "journal", "auth", "audit", "migration", "monitor"]

# PostgreSQL advisory lock ID — arbitrary, just needs to be unique per app.
# Any two processes that call pg_advisory_lock with the same ID will block
# until the first one releases (which happens automatically when the
# connection closes, even on crash).
_ADVISORY_LOCK_ID = 987654321

target_metadata = Base.metadata


def _get_url() -> str:
    """Read DATABASE_URL from the environment.

    The systemd EnvironmentFile (/etc/zerodha-mcp/.env) is loaded before
    this process starts, so os.environ is the only source of truth.
    """
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set.\n"
            "On the Oracle VM: check /etc/zerodha-mcp/.env\n"
            "Locally: export DATABASE_URL=postgresql+asyncpg://..."
        )
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def include_object(object, name, type_, reflected, compare_to):
    """Tell Alembic to only manage objects in our declared schemas.

    This prevents Alembic from touching pg_catalog, information_schema,
    or any other schema on the server.
    """
    if type_ == "table":
        return object.schema in MANAGED_SCHEMAS
    if type_ == "schema":
        return name in MANAGED_SCHEMAS
    return True


def run_migrations_offline() -> None:
    """Generate SQL scripts without a live DB connection.

    Used with: alembic upgrade head --sql > migration.sql
    Useful for reviewing what will run before touching production.
    """
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=include_object,
        version_table="alembic_version",
        version_table_schema="migration",
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=include_object,
        version_table="alembic_version",
        version_table_schema="migration",
        # Compare server defaults so Alembic detects server_default changes.
        compare_server_default=True,
        # Compare type length/precision changes.
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations against a live PostgreSQL server using asyncpg.

    Acquires a PostgreSQL session-level advisory lock before any DDL runs.
    The lock is released automatically when the connection closes, so it
    is safe against crashes and SIGKILL — it will never deadlock.
    """
    engine = create_async_engine(
        _get_url(),
        poolclass=pool.NullPool,  # migrations use a single connection, no pool
    )
    async with engine.connect() as connection:
        # Acquire advisory lock — blocks if another migration is in progress.
        # pg_try_advisory_lock would fail fast; pg_advisory_lock waits, which
        # is what we want during a deployment race.
        await connection.execute(
            text(f"SELECT pg_advisory_lock({_ADVISORY_LOCK_ID})")
        )

        # Ensure all managed schemas exist before Alembic touches any tables.
        # This is idempotent — safe to run on every deploy and on a blank DB.
        for schema in MANAGED_SCHEMAS:
            await connection.execute(
                text(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            )
        await connection.commit()

        await connection.run_sync(do_run_migrations)

        # Explicit unlock — belt-and-suspenders. The lock is also released
        # automatically when the connection closes at the end of this block.
        await connection.execute(
            text(f"SELECT pg_advisory_unlock({_ADVISORY_LOCK_ID})")
        )
        await connection.commit()

    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
