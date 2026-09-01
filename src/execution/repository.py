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
from datetime import UTC, datetime
from typing import Any

from src.db.config import get_session

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


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
            from src.db.models import OrderLog
        except ImportError:
            logger.warning("save_order skipped: sqlalchemy/models unavailable (dev env)")
            return None

        raw = result.get("body", result)
        try:
            raw_response = json.dumps(raw, default=str)
        except Exception:
            raw_response = str(raw)

        has_sl_or_target = bool(request.get("sl_trigger_price") or request.get("tgt_trigger_price"))
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
            sl_trigger_price=float(request["sl_trigger_price"]) if request.get("sl_trigger_price") else None,
            sl_limit_price=float(request["sl_limit_price"]) if request.get("sl_limit_price") else None,
            tgt_trigger_price=float(request["tgt_trigger_price"]) if request.get("tgt_trigger_price") else None,
            tgt_limit_price=float(request["tgt_limit_price"]) if request.get("tgt_limit_price") else None,
            trailing_sl_points=float(request["trailing_sl_points"]) if request.get("trailing_sl_points") else None,
            broker_order_id=result.get("order_id"),
            status=result.get("status") or "unknown",
            order_status=result.get("order_status"),
            raw_response=raw_response,
            created_at=_now(),
            sl_target_active=has_sl_or_target and (result.get("status") == "ok"),
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

    async def upsert_trailing_sl_state(
        self,
        *,
        order_id: str,
        exchange: str,
        security_id: str,
        side: str,
        broker: str,
        trail_points: float,
        sl_trigger_price: float,
        sl_limit_price: float,
    ) -> None:
        """Insert or update the live SL snapshot for one trailing order.
        Called on start AND on every successful ratchet — this is mutable
        current-state, unlike the immutable OrderLog snapshot. No-op (never
        raises) if the DB is unavailable, matching save_order()'s contract:
        a persistence failure must not interrupt the trailing-SL loop."""
        try:
            from src.db.models import TrailingSlState
        except ImportError:
            return
        try:
            async with get_session() as session:
                existing = await session.get(TrailingSlState, order_id)
                if existing is None:
                    session.add(TrailingSlState(
                        order_id=order_id, exchange=exchange, security_id=security_id,
                        side=side, broker=broker, trail_points=trail_points,
                        sl_trigger_price=sl_trigger_price, sl_limit_price=sl_limit_price,
                        active=True, updated_at=_now(),
                    ))
                else:
                    existing.sl_trigger_price = sl_trigger_price
                    existing.sl_limit_price = sl_limit_price
                    existing.active = True
                    existing.updated_at = _now()
                await session.flush()
        except RuntimeError as exc:
            logger.warning("upsert_trailing_sl_state skipped: %s", exc)
        except Exception as exc:
            logger.error("upsert_trailing_sl_state failed: %s", exc)

    async def deactivate_trailing_sl_state(self, order_id: str) -> None:
        """Mark a trailing order inactive (SL cancelled/triggered/order closed).
        No-op if the DB is unavailable or the row doesn't exist."""
        try:
            from src.db.models import TrailingSlState
        except ImportError:
            return
        try:
            async with get_session() as session:
                existing = await session.get(TrailingSlState, order_id)
                if existing is not None:
                    existing.active = False
                    existing.updated_at = _now()
                    await session.flush()
        except RuntimeError as exc:
            logger.warning("deactivate_trailing_sl_state skipped: %s", exc)
        except Exception as exc:
            logger.error("deactivate_trailing_sl_state failed: %s", exc)

    async def list_active_trailing_sl_state(self) -> list[dict]:
        """Return every row still marked active — used on process startup to
        rehydrate in-flight trailing-SL tasks. [] if the DB is unavailable."""
        try:
            from sqlalchemy import select

            from src.db.models import TrailingSlState
        except ImportError:
            return []
        try:
            async with get_session() as session:
                stmt = select(TrailingSlState).where(TrailingSlState.active.is_(True))
                result = await session.execute(stmt)
                return [_row_to_dict(r) for r in result.scalars().all()]
        except RuntimeError:
            return []
        except Exception as exc:
            logger.error("list_active_trailing_sl_state failed: %s", exc)
            return []

    async def find_active_smart_order_for_symbol(self, symbol: str) -> dict | None:
        """Return the most recent order for `symbol` still flagged
        sl_target_active — used by the positions page to show "this
        position has a live SL/target @ X" and to identify which
        broker_order_id a Modify action should call /smart/order/modify on.
        None if no active smart order is on file or the DB is unavailable.
        Best-effort by design: if two orders for the same symbol are both
        somehow still active (shouldn't happen — placing a new smart order
        doesn't deactivate an old one, only an explicit modify/cancel or the
        order-update listener does), the most recent one wins."""
        try:
            from sqlalchemy import select

            from src.db.models import OrderLog
        except ImportError:
            return None
        try:
            async with get_session() as session:
                stmt = (
                    select(OrderLog)
                    .where(OrderLog.symbol == symbol, OrderLog.sl_target_active.is_(True))
                    .order_by(OrderLog.created_at.desc())
                    .limit(1)
                )
                result = await session.execute(stmt)
                row = result.scalars().first()
                return _row_to_dict(row) if row is not None else None
        except RuntimeError:
            return None
        except Exception as exc:
            logger.error("find_active_smart_order_for_symbol failed: %s", exc)
            return None

    async def deactivate_sl_target(self, order_id: str) -> None:
        """Clear sl_target_active for the order with this broker_order_id —
        called after a successful modify-to-cancelled or when the position
        closes. No-op if the DB is unavailable or no matching row exists."""
        try:
            from sqlalchemy import select

            from src.db.models import OrderLog
        except ImportError:
            return
        try:
            async with get_session() as session:
                stmt = select(OrderLog).where(OrderLog.broker_order_id == order_id)
                result = await session.execute(stmt)
                row = result.scalars().first()
                if row is not None:
                    row.sl_target_active = False
                    await session.flush()
        except RuntimeError as exc:
            logger.warning("deactivate_sl_target skipped: %s", exc)
        except Exception as exc:
            logger.error("deactivate_sl_target failed: %s", exc)

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
