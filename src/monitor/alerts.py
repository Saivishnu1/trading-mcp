"""WhatsApp alert delivery via CallMeBot. Never raises — failures are logged
and reported as a bool so the caller can decide whether to persist/retry.
"""
from __future__ import annotations

import asyncio
import logging
import urllib.parse

import httpx

logger = logging.getLogger(__name__)


class WhatsAppAlerter:

    CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"
    MAX_RETRIES = 3
    _BACKOFF_SECONDS = (2, 4, 8)

    async def send(self, phone: str, api_key: str, message: str) -> bool:
        params = {"phone": phone, "text": message, "apikey": api_key}
        url = f"{self.CALLMEBOT_URL}?{urllib.parse.urlencode(params)}"
        for attempt in range(self.MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(url)
                    if r.status_code == 200:
                        return True
                    logger.warning("CallMeBot returned %s: %s", r.status_code, r.text[:200])
            except Exception as exc:
                logger.warning("CallMeBot send failed (attempt %d): %s", attempt + 1, exc)
            if attempt < self.MAX_RETRIES - 1:
                await asyncio.sleep(self._BACKOFF_SECONDS[attempt])
        return False

    async def send_position_alert(self, user: dict, position: dict, reason: str) -> bool:
        message = (
            f"POSITION ALERT\n"
            f"{position['symbol']} {position['strike']} {position['option_type']} "
            f"{position['expiry']}\n"
            f"Premium: {position['current_premium']}\n"
            f"P&L: {position['pnl']:+.0f}\n"
            f"Spot: {position['spot']}\n"
            f"Reason: {reason}"
        )
        return await self.send(user["whatsapp_phone"], user["callmebot_key"], message)

    async def send_market_alert(self, user: dict, symbol: str, condition: str, data: dict) -> bool:
        message = (
            f"MARKET ALERT — {symbol}\n"
            f"{condition}\n"
            f"Spot: {data['spot']}\n"
            f"PCR: {data.get('pcr', 'N/A')}\n"
            f"Time: {data['time']}"
        )
        return await self.send(user["whatsapp_phone"], user["callmebot_key"], message)

    async def send_morning_brief(self, user: dict, data: dict) -> bool:
        positions_str = "\n".join(
            f"  {p['symbol']} {p['strike']} {p['option_type']}: "
            f"{p['current_premium']:+.0f} (entry {p['entry_premium']})"
            for p in data.get("positions", [])
        ) or "  None"

        message = (
            f"MORNING BRIEF — {data['date']}\n"
            f"Expiry: {data['expiry']}\n"
            f"Nifty: {data['nifty']} | Sensex: {data['sensex']}\n"
            f"VIX: {data['vix']}\n"
            f"Global: {data['global_sentiment']}\n"
            f"Open positions:\n{positions_str}\n"
            f"Key levels: S {data['support']} | R {data['resistance']}"
        )
        return await self.send(user["whatsapp_phone"], user["callmebot_key"], message)

    async def send_eod_summary(self, user: dict, data: dict) -> bool:
        message = (
            f"EOD SUMMARY — {data['date']}\n"
            f"Nifty: {data['nifty_close']} ({data['nifty_change']:+.1f}%)\n"
            f"Sensex: {data['sensex_close']} ({data['sensex_change']:+.1f}%)\n"
            f"Realized P&L today: {data['realized_pnl']:+.0f}\n"
            f"Open positions: {data['open_count']}\n"
            f"Tomorrow: {data['tomorrow_note']}"
        )
        return await self.send(user["whatsapp_phone"], user["callmebot_key"], message)
