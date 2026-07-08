"""Alert delivery via CallMeBot (WhatsApp) and/or Telegram Bot API.

Never raises — failures are logged and reported as a bool so the caller can
decide whether to persist/retry. Both channels are optional per-user; send()
fans out to whichever is configured and succeeds if either one delivers.
Telegram has no onboarding handshake delay (unlike CallMeBot's WhatsApp
opt-in), so it's a useful fallback while/if CallMeBot is slow or down.
"""
from __future__ import annotations

import asyncio
import logging
import urllib.parse

import httpx

logger = logging.getLogger(__name__)


class WhatsAppAlerter:

    CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"
    TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"
    MAX_RETRIES = 3
    _BACKOFF_SECONDS = (2, 4, 8)

    async def _send_callmebot(self, phone: str, api_key: str, message: str) -> bool:
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

    async def _send_telegram(self, bot_token: str, chat_id: str, message: str) -> bool:
        url = self.TELEGRAM_URL.format(token=bot_token)
        for attempt in range(self.MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.post(url, json={"chat_id": chat_id, "text": message})
                    if r.status_code == 200:
                        return True
                    logger.warning("Telegram returned %s: %s", r.status_code, r.text[:200])
            except Exception as exc:
                logger.warning("Telegram send failed (attempt %d): %s", attempt + 1, exc)
            if attempt < self.MAX_RETRIES - 1:
                await asyncio.sleep(self._BACKOFF_SECONDS[attempt])
        return False

    async def send(self, phone: str, api_key: str, message: str, user: dict | None = None) -> bool:
        """Send via CallMeBot (phone/api_key) and Telegram (from user dict, if
        configured). Returns True if at least one channel delivered."""
        callmebot_ok = False
        if phone and api_key:
            callmebot_ok = await self._send_callmebot(phone, api_key, message)

        telegram_ok = False
        bot_token = (user or {}).get("telegram_bot_token")
        chat_id = (user or {}).get("telegram_chat_id")
        if bot_token and chat_id:
            telegram_ok = await self._send_telegram(bot_token, chat_id, message)

        return callmebot_ok or telegram_ok

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
        return await self.send(user["whatsapp_phone"], user["callmebot_key"], message, user)

    async def send_market_alert(self, user: dict, symbol: str, condition: str, data: dict) -> bool:
        message = (
            f"MARKET ALERT — {symbol}\n"
            f"{condition}\n"
            f"Spot: {data['spot']}\n"
            f"PCR: {data.get('pcr', 'N/A')}\n"
            f"Time: {data['time']}"
        )
        return await self.send(user["whatsapp_phone"], user["callmebot_key"], message, user)

    async def send_macro_alert(self, user: dict, alert_type: str, message_body: str) -> bool:
        """Generic macro/index-move alert — unlike send_market_alert, this
        doesn't assume a per-symbol Spot/PCR shape, since crude/gold/VIX/
        risk-off alerts aren't tied to an option chain. message_body is a
        pre-formatted, purely observational description (no signals/targets)."""
        message = f"MARKET INTELLIGENCE — {alert_type.upper()}\n{message_body}"
        return await self.send(user["whatsapp_phone"], user["callmebot_key"], message, user)

    async def send_morning_brief(self, user: dict, data: dict) -> bool:
        positions_str = "\n".join(
            f"  {p['symbol']} {p['strike']} {p['option_type']}: "
            f"{p['current_premium']:+.0f} (entry {p['entry_premium']})"
            for p in data.get("positions", [])
        ) or "  None"

        macro_note = data.get("macro_note")
        macro_line = f"{macro_note}\n" if macro_note else ""
        message = (
            f"MORNING BRIEF — {data['date']}\n"
            f"Expiry: {data['expiry']}\n"
            f"Nifty: {data['nifty']} | Sensex: {data['sensex']}\n"
            f"VIX: {data['vix']}\n"
            f"Global: {data['global_sentiment']}\n"
            f"{macro_line}"
            f"Open positions:\n{positions_str}\n"
            f"Key levels: S {data['support']} | R {data['resistance']}"
        )
        return await self.send(user["whatsapp_phone"], user["callmebot_key"], message, user)

    async def send_eod_summary(self, user: dict, data: dict) -> bool:
        message = (
            f"EOD SUMMARY — {data['date']}\n"
            f"Nifty: {data['nifty_close']} ({data['nifty_change']:+.1f}%)\n"
            f"Sensex: {data['sensex_close']} ({data['sensex_change']:+.1f}%)\n"
            f"Realized P&L today: {data['realized_pnl']:+.0f}\n"
            f"Open positions: {data['open_count']}\n"
            f"Tomorrow: {data['tomorrow_note']}"
        )
        return await self.send(user["whatsapp_phone"], user["callmebot_key"], message, user)
