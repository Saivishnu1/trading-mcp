"""Live order-update listener — pushes a Telegram alert the moment an order
fills, partially fills, or is rejected, instead of you having to poll /orders.

Consumes src/brokers/streaming.py::stream_order_updates() (real INDstocks WS
feed, confirmed working — see CLAUDE.md's WebSocket streaming entry) and
cross-references each push against the zerodha.orders audit log
(ExecutionRepository.find_by_broker_order_id) to attach the symbol/qty/side
the raw order_id alone doesn't carry.

Runs as a long-lived task alongside MarketMonitor.run() in the same process
(src/monitor/service.py) — one persistent WS connection for the whole
process, not one per order. Alerts go to the Telegram ADMIN bot/chat (the
same bot orders are placed from), not the per-user WhatsApp/Telegram alert
channel used by src/monitor/alerts.py, since order placement is an
admin-bot-only action.
"""
from __future__ import annotations

import logging

import httpx

from src.brokers.streaming import stream_order_updates
from src.execution.repository import ExecutionRepository

logger = logging.getLogger(__name__)

_TELEGRAM_SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"

# order_id -> last order_status we've already alerted on, so a duplicate push
# (heartbeat/retry) for an unchanged status doesn't spam the same message.
_last_alerted_status: dict[str, str] = {}


def _format_alert(order_id: str, order_status: str, logged: dict | None, update: dict) -> str:
    if logged:
        side = logged.get("transaction_type", "")
        symbol = logged.get("symbol") or logged.get("security_id", "")
        qty = logged.get("quantity", "")
        header = f"{side} {symbol} x{qty}"
    else:
        header = "Order"
    filled = update.get("filled_quantity")
    remaining = update.get("remaining_quantity")
    avg_price = update.get("average_price")
    lines = [f"📟 {header}", f"• Order ID: `{order_id}`", f"• Status: {order_status}"]
    if filled is not None:
        lines.append(f"• Filled: {filled}" + (f" / remaining {remaining}" if remaining is not None else ""))
    if avg_price:
        lines.append(f"• Avg price: ₹{avg_price:g}")
    return "\n".join(lines)


async def _send_telegram(bot_token: str, chat_id: str, message: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                _TELEGRAM_SEND_URL.format(token=bot_token),
                json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            )
            return r.status_code == 200
    except Exception as exc:
        logger.warning("order_update_listener: Telegram send failed: %s", exc)
        return False


async def run_order_update_listener(bot_token: str, chat_id: str) -> None:
    """Run forever, alerting on every order-status change. Never raises —
    stream_order_updates() already reconnects on drop; a malformed message or
    a failed alert send just logs and continues to the next push."""
    if not bot_token or not chat_id:
        logger.warning("order_update_listener: no admin bot token/chat_id configured — not starting.")
        return

    repo = ExecutionRepository()
    async for update in stream_order_updates():
        try:
            order_id = update.get("order_id")
            order_status = update.get("order_status")
            if not order_id or not order_status:
                continue
            if _last_alerted_status.get(order_id) == order_status:
                continue  # duplicate push for a status we already alerted on

            logged = await repo.find_by_broker_order_id(order_id)
            message = _format_alert(order_id, order_status, logged, update)
            sent = await _send_telegram(bot_token, chat_id, message)
            if sent:
                _last_alerted_status[order_id] = order_status
        except Exception as exc:  # pragma: no cover — defensive, must never kill the listener
            logger.error("order_update_listener: error handling update %s: %s", update, exc)
