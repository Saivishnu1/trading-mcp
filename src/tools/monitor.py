from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from src import meta as _meta
from src.monitor.alerts import WhatsAppAlerter
from src.monitor.repository import MonitorRepository


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

        Each tracked position includes a "broker" field ("zerodha" | "indmoney")
        showing which account it was synced from; positions_by_broker gives a
        quick per-broker count so it's visible at a glance whether positions
        are coming from Zerodha, INDmoney, or both.

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

        positions_by_broker: dict[str, int] = {}
        for pos in positions:
            broker_name = pos.get("broker", "unknown")
            positions_by_broker[broker_name] = positions_by_broker.get(broker_name, 0) + 1

        # Piece B diagnostic (2026-07-11) — did the last check_market_conditions
        # poll's NIFTY/SENSEX spot come from LivePriceCache (the WS feed) or
        # the REST option-chain fallback, and how stale is that reading.
        checked_at = (session_state or {}).get("live_price_checked_at")
        age_seconds = None
        if checked_at:
            age_seconds = (datetime.now(timezone.utc) - datetime.fromisoformat(checked_at)).total_seconds()
        live_price_cache = {
            "checked_at": checked_at,
            "age_seconds": age_seconds,
            "nifty": {
                "ltp": (session_state or {}).get("live_price_nifty_ltp"),
                "cache_hit": bool((session_state or {}).get("live_price_nifty_cache_hit")),
            },
            "sensex": {
                "ltp": (session_state or {}).get("live_price_sensex_ltp"),
                "cache_hit": bool((session_state or {}).get("live_price_sensex_cache_hit")),
            },
        }

        data = {
            "user": user["name"],
            "running": last_heartbeat is not None,
            "healthy": healthy,
            "status": status,
            "positions": enriched,
            "positions_by_broker": positions_by_broker,
            "alert_count_today": len(alerts_today),
            "heartbeat": heartbeat,
            "live_price_cache": live_price_cache,
        }
        return _meta.wrap(data, _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_VALID,
            source="monitor schema",
        ))

    @mcp.tool()
    async def get_recent_alerts(hours: int = 24, include_undelivered: bool = False) -> dict:
        """Return WhatsApp alerts sent in the last N hours by the position monitor.

        Args:
            hours: lookback window in hours (default 24).
            include_undelivered: also include raw touch-log rows that were
                never actually pushed (e.g. a wall-hold that reverted before
                confirmation — see check_oi_walls). Confirmed bug
                (2026-07-13): these were always included with no way to
                filter them out, making OI_WALL_BREAK look like it fires on
                first touch even though the scheduler only pushes it to
                Telegram after a sustained hold. Default False now matches
                this tool's own docstring ("alerts sent").

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
        if not include_undelivered:
            alerts = [a for a in alerts if a.get("delivered")]
        return _meta.wrap({"alerts": alerts}, _meta.build_meta(
            type_=_meta.TYPE_FACT,
            validation_status=_meta.VALIDATION_VERIFIED,
            data_quality=_meta.DQ_VALID,
            source="monitor.alerts",
        ))

    _MARKET_ALERT_TYPES = {
        "macro_crude", "macro_gold", "macro_vix", "macro_risk_off",
        "index_move_nifty", "index_move_sensex",
        "oi_call_wall_break", "oi_put_wall_break", "oi_wall_rejection",
        "pinning_risk", "pcr_shift",
    }

    @mcp.tool()
    async def get_market_alerts(hours: int = 24, include_undelivered: bool = False) -> dict:
        """Return market intelligence alerts sent in the last N hours —
        macro (crude/gold/VIX/risk-off), NIFTY/SENSEX index moves, OI wall
        breaks/rejections, pinning risk, and PCR shifts. Excludes
        per-position alerts (trailing SL, profit milestones); use
        get_recent_alerts for those.

        Args:
            hours: lookback window in hours (default 24).
            include_undelivered: also include raw touch-log rows never
                actually pushed to Telegram (see get_recent_alerts). Confirmed
                bug (2026-07-13): these were always included with no way to
                filter them out, making OI_WALL_BREAK look like it fires on
                first touch instead of only after a sustained hold.

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
        all_alerts = await repo.get_recent_alerts(users[0]["id"], hours=hours)
        market_alerts = [a for a in all_alerts if a.get("alert_type") in _MARKET_ALERT_TYPES]
        if not include_undelivered:
            market_alerts = [a for a in market_alerts if a.get("delivered")]
        return _meta.wrap({"alerts": market_alerts}, _meta.build_meta(
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
        crude_move_threshold: float | None = None,
        gold_move_threshold: float | None = None,
        nifty_move_threshold: float | None = None,
        sensex_move_threshold: float | None = None,
        risk_off_count_threshold: int | None = None,
    ) -> dict:
        """Update the position monitor's alert thresholds without restarting the service.

        Args:
            pcr_shift_threshold: absolute PCR shift that triggers a market alert.
            vix_spike_threshold: India VIX level that triggers a market alert.
            profit_alert_pct: position profit fraction (e.g. 0.5 = +50%) that triggers a milestone alert.
            crude_move_threshold: crude oil % move that triggers a macro alert (default 2.0).
            gold_move_threshold: gold % move that triggers a macro alert (default 1.5).
            nifty_move_threshold: NIFTY % move since the last check that triggers an alert (default 1.0).
            sensex_move_threshold: SENSEX % move since the last check that triggers an alert (default 1.0).
            risk_off_count_threshold: number of aligned risk-off signals (of 3: crude up,
                gold up, S&P down) required to trigger the combined risk-off alert (default 3).

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
        if crude_move_threshold is not None:
            updates["crude_move_threshold"] = crude_move_threshold
        if gold_move_threshold is not None:
            updates["gold_move_threshold"] = gold_move_threshold
        if nifty_move_threshold is not None:
            updates["nifty_move_threshold"] = nifty_move_threshold
        if sensex_move_threshold is not None:
            updates["sensex_move_threshold"] = sensex_move_threshold
        if risk_off_count_threshold is not None:
            updates["risk_off_count_threshold"] = risk_off_count_threshold

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
