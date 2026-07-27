"""Priority 1 — Timeframe Engine: policy table unit tests.

TP-1  every horizon has at least one EXECUTION interval
TP-2  an interval absent from a horizon's policy is DISALLOWED, not silently daily
TP-3  can_gate_entry is True only for EXECUTION/FINE_ENTRY, never CONTEXT/DISALLOWED
TP-4  intraday-options weekly/monthly are DISALLOWED outright (not merely context)
TP-5  daily is CONTEXT (not EXECUTION) for intraday options — never gates that horizon's entry
TP-6  swing/positional context intervals never gate entry either
"""
from __future__ import annotations

import pytest

from src.timeframe.policy import (
    HoldingHorizon,
    TimeframeRole,
    can_gate_entry,
    context_intervals,
    execution_intervals,
    role_for,
)


class TestTP1EveryHorizonHasExecution:
    @pytest.mark.parametrize("horizon", list(HoldingHorizon))
    def test_has_at_least_one_execution_interval(self, horizon):
        assert len(execution_intervals(horizon)) >= 1


class TestTP2UnknownIntervalIsDisallowed:
    def test_random_interval_disallowed_for_intraday(self):
        assert role_for(HoldingHorizon.INTRADAY_OPTIONS, "week") == TimeframeRole.DISALLOWED

    def test_month_disallowed_for_intraday_options(self):
        assert role_for(HoldingHorizon.INTRADAY_OPTIONS, "month") == TimeframeRole.DISALLOWED

    def test_garbage_string_disallowed(self):
        assert role_for(HoldingHorizon.SWING, "not_a_real_interval") == TimeframeRole.DISALLOWED


class TestTP3CanGateEntryOnlyForExecutionRoles:
    def test_execution_can_gate(self):
        assert can_gate_entry(HoldingHorizon.INTRADAY_OPTIONS, "15minute") is True

    def test_fine_entry_can_gate(self):
        assert can_gate_entry(HoldingHorizon.INTRADAY_OPTIONS, "1minute") is True

    def test_context_cannot_gate(self):
        assert can_gate_entry(HoldingHorizon.INTRADAY_OPTIONS, "day") is False

    def test_disallowed_cannot_gate(self):
        assert can_gate_entry(HoldingHorizon.INTRADAY_OPTIONS, "week") is False


class TestTP4IntradayOptionsExcludesHigherTimeframes:
    def test_weekly_disallowed(self):
        assert role_for(HoldingHorizon.INTRADAY_OPTIONS, "week") == TimeframeRole.DISALLOWED

    def test_monthly_disallowed(self):
        assert role_for(HoldingHorizon.INTRADAY_OPTIONS, "month") == TimeframeRole.DISALLOWED


class TestTP5DailyIsContextOnlyForIntradayOptions:
    def test_daily_role_is_context(self):
        assert role_for(HoldingHorizon.INTRADAY_OPTIONS, "day") == TimeframeRole.CONTEXT

    def test_daily_in_context_intervals_list(self):
        assert "day" in context_intervals(HoldingHorizon.INTRADAY_OPTIONS)

    def test_daily_not_in_execution_intervals_list(self):
        assert "day" not in execution_intervals(HoldingHorizon.INTRADAY_OPTIONS)


class TestTP6SwingAndPositionalContextNeverGates:
    def test_swing_weekly_context_cannot_gate(self):
        assert role_for(HoldingHorizon.SWING, "week") == TimeframeRole.CONTEXT
        assert can_gate_entry(HoldingHorizon.SWING, "week") is False

    def test_positional_monthly_context_cannot_gate(self):
        assert role_for(HoldingHorizon.POSITIONAL, "month") == TimeframeRole.CONTEXT
        assert can_gate_entry(HoldingHorizon.POSITIONAL, "month") is False

    def test_positional_execution_is_daily(self):
        assert role_for(HoldingHorizon.POSITIONAL, "day") == TimeframeRole.EXECUTION
