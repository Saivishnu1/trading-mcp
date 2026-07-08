"""Tests for src/telegram_admin/service_manager.py.

Root cause under test: env var updates (e.g. INDSTOCKS_TOKEN) via the
Telegram /env flow only ever restarted zerodha-mcp, leaving the separate
zerodha-monitor process running on a stale value indefinitely since both
services read the same /etc/zerodha-mcp/.env file. restart_service() must
restart every service in RESTART_SERVICES, and are_restart_services_active()
must report per-service status so a caller never claims success when only
one of the two processes actually came back up.
"""
from __future__ import annotations

import subprocess
from unittest.mock import patch, MagicMock

from src.telegram_admin import service_manager
from src.telegram_admin.config import RESTART_SERVICES


class TestRestartServiceCoversBoth:
    def test_restarts_every_service_in_restart_services(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            service_manager.restart_service()

        restarted = [call.args[0][-1] for call in mock_run.call_args_list]
        assert restarted == RESTART_SERVICES
        assert "zerodha-mcp" in restarted
        assert "zerodha-monitor" in restarted

    def test_raises_if_any_service_restart_fails(self):
        def _side_effect(cmd, **kwargs):
            if cmd[-1] == "zerodha-monitor":
                raise subprocess.CalledProcessError(1, cmd, stderr="failed")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=_side_effect):
            try:
                service_manager.restart_service()
                assert False, "expected CalledProcessError to propagate"
            except subprocess.CalledProcessError:
                pass

    def test_stops_at_first_failure_does_not_restart_remaining_services(self):
        calls = []

        def _side_effect(cmd, **kwargs):
            calls.append(cmd[-1])
            if cmd[-1] == "zerodha-mcp":
                raise subprocess.CalledProcessError(1, cmd, stderr="failed")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=_side_effect):
            try:
                service_manager.restart_service()
            except subprocess.CalledProcessError:
                pass

        assert calls == ["zerodha-mcp"]


class TestAreRestartServicesActive:
    def test_reports_status_per_service(self):
        def _side_effect(cmd, **kwargs):
            service = cmd[-1]
            if service == "zerodha-mcp":
                return MagicMock(stdout="active\n", returncode=0)
            exc = subprocess.CalledProcessError(3, cmd)
            exc.stdout = "inactive\n"
            raise exc

        with patch("subprocess.run", side_effect=_side_effect):
            result = service_manager.are_restart_services_active()

        assert result == {"zerodha-mcp": True, "zerodha-monitor": False}

    def test_all_active(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="active\n", returncode=0)
            result = service_manager.are_restart_services_active()

        assert all(result.values())
        assert set(result.keys()) == set(RESTART_SERVICES)


class TestIsServiceActiveUnaffected:
    """is_service_active() still checks only the primary SERVICE_NAME —
    confirms the refactor into _is_active() didn't change its contract."""

    def test_is_service_active_checks_primary_service_only(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="active\n", returncode=0)
            assert service_manager.is_service_active() is True

        called_service = mock_run.call_args.args[0][-1]
        assert called_service == "zerodha-mcp"
