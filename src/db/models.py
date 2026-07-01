"""SQLAlchemy ORM models — one-to-one mapping of the existing SQLite schema.

These are the PostgreSQL representations of the tables that already exist in
SQLite (src/journal/db.py schema v7). Alembic reads these to generate
migrations — it does NOT run CREATE TABLE directly.

Schema assignment:
  zerodha   → trades
  journal   → recommendation_log
  auth      → sessions, api_keys
  audit     → (reserved for future append-only audit rows)
  migration → (Turso import staging — always empty in normal operation)
"""
from __future__ import annotations

try:
    from sqlalchemy import (
        BigInteger,
        Boolean,
        CheckConstraint,
        Float,
        Index,
        Integer,
        Text,
        text,
    )
    from sqlalchemy.orm import Mapped, mapped_column

    from .base import Base

    # -------------------------------------------------------------------------
    # zerodha.trades
    # -------------------------------------------------------------------------

    class Trade(Base):
        __tablename__ = "trades"
        __table_args__ = (
            Index("ix_trades_symbol",      "symbol"),
            Index("ix_trades_status",      "status"),
            Index("ix_trades_entry_date",  "entry_date"),
            Index("ix_trades_trade_type",  "trade_type"),
            Index("ix_trades_external_id", "external_id"),
            {"schema": "zerodha"},
        )

        id: Mapped[str]               = mapped_column(Text, primary_key=True)
        symbol: Mapped[str]           = mapped_column(Text, nullable=False)
        trade_type: Mapped[str]       = mapped_column(Text, nullable=False, server_default="EQUITY")
        direction: Mapped[str]        = mapped_column(Text, nullable=False)
        strategy: Mapped[str | None]  = mapped_column(Text)
        entry_price: Mapped[float]    = mapped_column(Float, nullable=False)
        quantity: Mapped[int | None]  = mapped_column(Integer)
        entry_date: Mapped[str]       = mapped_column(Text, nullable=False)
        entry_time: Mapped[str]       = mapped_column(Text, nullable=False)
        rationale: Mapped[str | None] = mapped_column(Text)
        stoploss: Mapped[float | None]  = mapped_column(Float)
        target: Mapped[float | None]    = mapped_column(Float)
        risk_reward: Mapped[float | None] = mapped_column(Float)
        regime: Mapped[str | None]    = mapped_column(Text)
        signal: Mapped[str | None]    = mapped_column(Text)
        risk_score: Mapped[int | None] = mapped_column(Integer)
        analysis_snapshot: Mapped[str | None] = mapped_column(Text)
        created_by: Mapped[str]       = mapped_column(Text, nullable=False, server_default="MANUAL")
        status: Mapped[str]           = mapped_column(Text, nullable=False, server_default="OPEN")
        exit_price: Mapped[float | None]  = mapped_column(Float)
        exit_date: Mapped[str | None]     = mapped_column(Text)
        exit_time: Mapped[str | None]     = mapped_column(Text)
        exit_reason: Mapped[str | None]   = mapped_column(Text)
        pnl: Mapped[float | None]         = mapped_column(Float)
        pnl_percent: Mapped[float | None] = mapped_column(Float)
        holding_days: Mapped[int | None]  = mapped_column(Integer)
        tags: Mapped[str | None]          = mapped_column(Text)
        notes: Mapped[str | None]         = mapped_column(Text)
        # v2 immutable entry-time snapshots
        risk_amount: Mapped[float | None]             = mapped_column(Float)
        capital_at_risk: Mapped[float | None]         = mapped_column(Float)
        portfolio_heat_at_entry: Mapped[float | None] = mapped_column(Float)
        # v3 deduplication key
        external_id: Mapped[str | None] = mapped_column(Text)
        created_at: Mapped[str]         = mapped_column(Text, nullable=False)
        updated_at: Mapped[str]         = mapped_column(Text, nullable=False)
        # v7 multi-user isolation
        user_id: Mapped[str | None] = mapped_column(Text, index=True)

    # -------------------------------------------------------------------------
    # journal.recommendation_log
    # -------------------------------------------------------------------------

    class RecommendationLog(Base):
        __tablename__ = "recommendation_log"
        __table_args__ = (
            CheckConstraint(
                "recommendation_type IN ("
                "'ENTER','EXIT','HOLD','AVOID','OBSERVE',"
                "'STAY_CASH','SIZE_REDUCE','TAKE_PROFIT','TIGHTEN_STOP','NONE')",
                name="valid_recommendation_type",
            ),
            CheckConstraint(
                "uncertainty_level IN ('LOW','MEDIUM','HIGH')",
                name="valid_uncertainty_level",
            ),
            CheckConstraint(
                "capture_mode IN ('manual','auto','baseline')",
                name="valid_capture_mode",
            ),
            Index("ix_recommendation_log_symbol",    "symbol"),
            Index("ix_recommendation_log_timestamp", "timestamp"),
            Index("ix_recommendation_log_user_id",   "user_id"),
            {"schema": "journal"},
        )

        id: Mapped[str]                          = mapped_column(Text, primary_key=True)
        timestamp: Mapped[str]                   = mapped_column(Text, nullable=False)
        symbol: Mapped[str | None]               = mapped_column(Text)
        market_snapshot: Mapped[str | None]      = mapped_column(Text)
        mcp_facts: Mapped[str | None]            = mapped_column(Text)
        user_action: Mapped[str | None]          = mapped_column(Text)
        outcome_1d: Mapped[float | None]         = mapped_column(Float)
        outcome_5d: Mapped[float | None]         = mapped_column(Float)
        outcome_20d: Mapped[float | None]        = mapped_column(Float)
        claude_reasoning_summary: Mapped[str | None] = mapped_column(Text)
        recommendation_type: Mapped[str | None]  = mapped_column(Text)
        uncertainty_level: Mapped[str | None]    = mapped_column(Text)
        mcp_changed_decision: Mapped[int | None] = mapped_column(Integer)
        would_have_acted_without_mcp: Mapped[int | None] = mapped_column(Integer)
        decision_quality: Mapped[str | None]     = mapped_column(Text)
        postmortem_helpful: Mapped[int | None]   = mapped_column(Integer)
        postmortem_why: Mapped[str | None]       = mapped_column(Text)
        postmortem_review_questions: Mapped[str | None] = mapped_column(Text)
        bootstrap_period: Mapped[int]            = mapped_column(Integer, server_default=text("1"))
        bias_contaminated: Mapped[int]           = mapped_column(Integer, server_default=text("1"))
        baseline_no_mcp: Mapped[int]             = mapped_column(Integer, server_default=text("0"))
        capture_mode: Mapped[str]                = mapped_column(Text, server_default="manual")
        created_at: Mapped[str]                  = mapped_column(Text, nullable=False)
        updated_at: Mapped[str]                  = mapped_column(Text, nullable=False)
        user_id: Mapped[str | None]              = mapped_column(Text)

    # -------------------------------------------------------------------------
    # auth.sessions
    # -------------------------------------------------------------------------

    class Session(Base):
        __tablename__ = "sessions"
        __table_args__ = (
            Index("ix_sessions_user_id",   "user_id"),
            Index("ix_sessions_is_active", "is_active"),
            {"schema": "auth"},
        )

        # Sessions table uses a composite natural key (user_id + enctoken).
        # We add a surrogate PK for ORM compatibility.
        id: Mapped[int]          = mapped_column(Integer, primary_key=True, autoincrement=True)
        user_id: Mapped[str]     = mapped_column(Text, nullable=False)
        enctoken: Mapped[str]    = mapped_column(Text, nullable=False)
        created_at: Mapped[str]  = mapped_column(Text, nullable=False)
        last_used: Mapped[str]   = mapped_column(Text, nullable=False)
        is_active: Mapped[int]   = mapped_column(Integer, nullable=False, server_default=text("1"))

    # -------------------------------------------------------------------------
    # auth.api_keys
    # -------------------------------------------------------------------------

    class ApiKey(Base):
        __tablename__ = "api_keys"
        __table_args__ = (
            Index("ix_api_keys_user_id",   "user_id"),
            Index("ix_api_keys_is_active", "is_active"),
            {"schema": "auth"},
        )

        api_key: Mapped[str]      = mapped_column(Text, primary_key=True)
        user_id: Mapped[str]      = mapped_column(Text, nullable=False)
        created_at: Mapped[str]   = mapped_column(Text, nullable=False)
        last_used: Mapped[str | None] = mapped_column(Text)
        is_active: Mapped[int]    = mapped_column(Integer, nullable=False, server_default=text("1"))

except ImportError:
    pass  # SQLAlchemy not installed — Windows dev environment
