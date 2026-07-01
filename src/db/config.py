"""Async SQLAlchemy engine + session factory for PostgreSQL.

Loaded only when DATABASE_URL is set. Application code that needs
the session should call get_session() as an async context manager.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

# Guard: do not crash on Windows dev where asyncpg is not installed.
try:
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    _ASYNCPG_AVAILABLE = True
except ImportError:
    _ASYNCPG_AVAILABLE = False

_engine = None
_session_factory = None


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Set it in /etc/zerodha-mcp/.env or the environment."
        )
    # SQLAlchemy requires the asyncpg driver scheme.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def get_engine():
    global _engine
    if _engine is None:
        if not _ASYNCPG_AVAILABLE:
            raise RuntimeError("asyncpg/sqlalchemy not installed — cannot create engine.")
        _engine = create_async_engine(
            _get_database_url(),
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=os.environ.get("DB_ECHO", "").lower() in ("1", "true"),
        )
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager that yields a database session and auto-commits or rolls back."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_engine() -> None:
    """Dispose the engine — call on application shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
