"""Async repository for the zerodha.orders table — thin wrapper over SQLAlchemy.

Mirrors src/monitor/repository.py: methods take/return plain dicts, timestamps
are ISO-8601 strings, ORM models are imported lazily so this module stays
importable on Windows dev (where sqlalchemy/asyncpg are absent — see
src/db/config.py and the try/except in src/db/models.py).

If no database is configured (DATABASE_URL unset, e.g. Windows/Railway dev),
save_order() logs a warning and returns None rather than raising — placing an
order must never fail just because the audit log is unavailable.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from src.db.config import get_session

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: Any) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


class ExecutionRepository:
    """Data access for the zerodha.orders audit log. Stateless/reusable."""

    async def save_order(
        self,
        *,
        user_id: str | None,
        broker: str,
        source: str,
        request: dict,
        result: dict,
    ) -> dict | None:
        """Persist one submitted order. Returns the stored row as a dict, or
        None if the DB is unavailable (never raises for that reason).

        Args:
            request: the OrderRequest.to_dict() intent snapshot.
            result:  the broker place_order() response dict.
        """
        try:
            from sqlalchemy.exc import SQLAlchemyError  # noqa: F401 (import guard)
            from src.db.models import OrderLog
        except ImportError:
            logger.warning("save_order skipped: sqlalchemy/models unavailable (dev env)")
            return None

        raw = result.get("body", result)
        try:
            raw_response = json.dumps(raw, default=str)
        except Exception:
            raw_response = str(raw)

        row_kwargs = dict(
            id=str(uuid.uuid4()),
            user_id=user_id,
            broker=broker,
            source=source,
            symbol=request.get("symbol") or None,
            security_id=str(request.get("security_id") or ""),
            exchange=request.get("exchange") or "",
            segment=request.get("segment") or None,
            transaction_type=request.get("transaction_type") or "",
            quantity=int(request.get("quantity") or 0),
            order_type=request.get("order_type") or "",
            product=request.get("product") or None,
            limit_price=float(request["limit_price"]) if request.get("limit_price") else None,
            broker_order_id=result.get("order_id"),
            status=result.get("status") or "unknown",
            order_status=result.get("order_status"),
            raw_response=raw_response,
            created_at=_now(),
        )
        try:
            async with get_session() as session:
                row = OrderLog(**row_kwargs)
                session.add(row)
                await session.flush()
                return _row_to_dict(row)
        except RuntimeError as exc:
            # DATABASE_URL not set (get_session/get_engine raise RuntimeError).
            logger.warning("save_order skipped: %s", exc)
            return None
        except Exception as exc:
            logger.error("save_order failed: %s", exc)
            return None

    async def find_by_broker_order_id(self, broker_order_id: str) -> dict | None:
        """Look up the logged order (and its symbol/qty/side snapshot) that
        produced this broker_order_id — used to enrich a live WS order-update
        push with human-readable context. None if not found or DB down."""
        try:
            from sqlalchemy import select
            from src.db.models import OrderLog
        except ImportError:
            return None
        try:
            async with get_session() as session:
                stmt = select(OrderLog).where(OrderLog.broker_order_id == broker_order_id)
                result = await session.execute(stmt)
                row = result.scalars().first()
                return _row_to_dict(row) if row is not None else None
        except RuntimeError:
            return None
        except Exception as exc:
            logger.error("find_by_broker_order_id failed: %s", exc)
            return None

    async def recent_orders(self, user_id: str | None = None, limit: int = 20) -> list[dict]:
        """Return the most recent submitted orders (newest first). [] if DB down."""
        try:
            from sqlalchemy import select
            from src.db.models import OrderLog
        except ImportError:
            return []
        try:
            async with get_session() as session:
                stmt = select(OrderLog)
                if user_id is not None:
                    stmt = stmt.where(OrderLog.user_id == user_id)
                stmt = stmt.order_by(OrderLog.created_at.desc()).limit(limit)
                result = await session.execute(stmt)
                return [_row_to_dict(r) for r in result.scalars().all()]
        except RuntimeError:
            return []
        except Exception as exc:
            logger.error("recent_orders failed: %s", exc)
            return []
