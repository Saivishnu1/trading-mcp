from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP
from src import meta as _meta

from src.monitor.repository import MonitorRepository
from src.monitor.alerts import WhatsAppAlerter


def _staleness(last_heartbeat: str | None) -> tuple[bool, str]:
    """Return (healthy, status) by comparing last_heartbeat against
    MarketMonitor.STALE_AFTER_SECONDS — twice the slowest adaptive poll
    interval, so a slow-but-alive loop never false-positives as dead."""
    from src.monitor.scheduler import MarketMonitor

    if last_heartbeat is None:
        return False, "NEVER_STARTED"
    age_seconds = (datetime.now(timezone.utc) - datetime.fromisoformat(last_heartbeat)).total_seconds()
    if age_seconds > MarketMonitor.STALE_AFTER_SECONDS:
        return False, "STALE"
    return True, "ACTIVE"


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def sync_positions() -> dict:
        """Manually trigger an immediate position sync from the broker(s) into
        the monitor's tracked positions, instead of waiting for the next
        scheduled sync (every 30 minutes during market hours).

        No authentication required — the monitor service holds its own broker
        session independently of the calling client's auth state.
        """
        from src.monitor.position_tracker import PositionTracker

        repo = MonitorRepository()
        users = await repo.get_active_users()
        if not users:
            return _meta.make_symbol_error("", "sync_positions")
        user = users[0]

        tracker = PositionTracker(repo=repo)
        await tracker.sync_from_broker(user)
        positions = await repo.get_active_positions(user["id"])

        return _meta.wrap({"synced_count": len(positions), "positions": positions}, _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_VALID,
            source="broker positions API",
        ))

    @mcp.tool()
    async def get_monitor_status() -> dict:
        """Return the Phase 9A background monitor's current state: tracked
        positions, trailing SL levels, today's alert count, and heartbeat
        timestamps so you can tell if the systemd service is alive without
        SSHing into the Oracle VM.

        No authentication required — reads the monitor.* Postgres schema directly.
        """
        repo = MonitorRepository()
        users = await repo.get_active_users()
        if not users:
            return _meta.wrap(
                {"status": "no_user_configured", "positions": []},
                _meta.build_meta(
                    type_=_meta.TYPE_FACT,
                    validation_status=_meta.VALIDATION_VERIFIED,
                    data_quality=_meta.DQ_INVALID,
                    source="monitor.users",
                ),
            )
        user = users[0]
        positions = await repo.get_active_positions(user["id"])
        enriched = []
        for pos in positions:
            peak = await repo.get_peak(pos["id"])
            enriched.append({**pos, "peak": peak})
        session_state = await repo.get_session_state(user["id"])
        last_heartbeat = (session_state or {}).get("last_heartbeat")
        healthy, status = _staleness(last_heartbeat)
        heartbeat = {
            "last_heartbeat": last_heartbeat,
            "last_market_check": (session_state or {}).get("last_market_check"),
            "last_position_check": (session_state or {}).get("last_position_check"),
            "last_alert_sent": (session_state or {}).get("last_alert_sent"),
        }
        alerts_today = await repo.get_recent_alerts(user["id"], hours=24)

        data = {
            "user": user["name"],
            "running": last_heartbeat is not None,
            "healthy": healthy,
            "status": status,
            "positions": enriched,
            "alert_count_today": len(alerts_today),
            "heartbeat": heartbeat,
        }
        return _meta.wrap(data, _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_VALID,
            source="monitor schema",
        ))

    @mcp.tool()
    async def get_recent_alerts(hours: int = 24) -> dict:
        """Return WhatsApp alerts sent in the last N hours by the position monitor.

        Args:
            hours: lookback window in hours (default 24).

        No authentication required.
        """
        repo = MonitorRepository()
        users = await repo.get_active_users()
        if not users:
            return _meta.wrap({"alerts": []}, _meta.build_meta(
                type_=_meta.TYPE_FACT,
                validation_status=_meta.VALIDATION_VERIFIED,
                data_quality=_meta.DQ_INVALID,
                source="monitor.users",
            ))
        alerts = await repo.get_recent_alerts(users[0]["id"], hours=hours)
        return _meta.wrap({"alerts": alerts}, _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_VALID,
            source="monitor.alerts",
        ))

    @mcp.tool()
    async def update_monitor_settings(
        pcr_shift_threshold: float | None = None,
        vix_spike_threshold: float | None = None,
        profit_alert_pct: float | None = None,
    ) -> dict:
        """Update the position monitor's alert thresholds without restarting the service.

        Args:
            pcr_shift_threshold: absolute PCR shift that triggers a market alert.
            vix_spike_threshold: India VIX level that triggers a market alert.
            profit_alert_pct: position profit fraction (e.g. 0.5 = +50%) that triggers a milestone alert.

        No authentication required.
        """
        from sqlalchemy import select
        from src.db.base import get_session
        from src.db.models import MonitorSettings

        repo = MonitorRepository()
        users = await repo.get_active_users()
        if not users:
            return _meta.make_symbol_error("", "update_monitor_settings")
        user_id = users[0]["id"]

        updates = {}
        if pcr_shift_threshold is not None:
            updates["pcr_shift_threshold"] = pcr_shift_threshold
        if vix_spike_threshold is not None:
            updates["vix_spike_threshold"] = vix_spike_threshold
        if profit_alert_pct is not None:
            updates["profit_alert_pct"] = profit_alert_pct

        if updates:
            from datetime import datetime, timezone
            async with get_session() as session:
                result = await session.execute(
                    select(MonitorSettings).where(MonitorSettings.user_id == user_id)
                )
                row = result.scalar_one_or_none()
                if row is not None:
                    for k, v in updates.items():
                        setattr(row, k, v)
                    row.updated_at = datetime.now(timezone.utc).isoformat()

        settings = await repo.get_user_settings(user_id)
        return _meta.wrap({"settings": settings, "updated": list(updates.keys())}, _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_VALID,
            source="monitor.settings",
        ))

    @mcp.tool()
    async def test_whatsapp_alert(message_type: str = "position") -> dict:
        """Send a test WhatsApp message via CallMeBot to verify monitor alert delivery.

        Args:
            message_type: one of "position" | "market" | "morning" | "eod".
                "morning"/"eod" fetch real Nifty/Sensex/VIX/key-levels data
                through MarketMonitor (the same code path the scheduler uses),
                not a hardcoded payload — so this actually exercises the data
                wiring, not just delivery.

        No authentication required.
        """
        repo = MonitorRepository()
        users = await repo.get_active_users()
        if not users:
            return _meta.make_symbol_error("", "test_whatsapp_alert")
        user = users[0]
        alerter = WhatsAppAlerter()

        if message_type == "position":
            delivered = await alerter.send_position_alert(user, {
                "symbol": "NIFTY", "strike": 24400, "option_type": "CE",
                "expiry": "2026-07-09", "current_premium": 120.0,
                "pnl": 500.0, "spot": 24380.0,
            }, "Test alert")
        elif message_type == "market":
            delivered = await alerter.send_market_alert(user, "NIFTY", "Test condition", {
                "spot": 24380.0, "pcr": 1.1, "time": "12:00",
            })
        elif message_type == "morning":
            from src.monitor.scheduler import MarketMonitor
            delivered = await MarketMonitor().send_morning_brief(user)
        elif message_type == "eod":
            from src.monitor.scheduler import MarketMonitor
            delivered = await MarketMonitor().send_eod_summary(user)
        else:
            return _meta.make_symbol_error(message_type, "test_whatsapp_alert")

        return _meta.wrap({"delivered": delivered, "message_type": message_type}, _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_UNVALIDATED,
            data_quality=_meta.DQ_VALID if delivered else _meta.DQ_INVALID,
            source="CallMeBot",
        ))
