import asyncio
import logging
import os
from telegram import BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from src.telegram_admin.config import BOT_TOKEN
from src.telegram_admin.handlers import (
    start_command,
    help_command,
    admin_command,
    admin_menu_callback,
    admin_cmd_callback,
    restart_command,
    cmd_restart_callback,
    show_command,
    status_command,
    health_command,
    tail_command,
    logs_command,
    backup_command,
    backup_env_command,
    backup_env_callback,
    reload_command,
    disk_command,
    uptime_command,
    ip_command,
    cancel_command,
    buy_command,
    sell_command,
    order_confirm_callback,
    positions_command,
    orders_command,
    search_command,
)
from src.telegram_admin.conversation import env_conversation_handler

logger = logging.getLogger(__name__)

# Shown in Telegram's native "/" autocomplete menu — deliberately just the
# daily-trading commands + /admin + /help/cancel, NOT all 21 commands, so
# the picker isn't a wall of rarely-used ops/debugging entries. Everything
# else (status, health, restart, logs, backups, config) is still fully
# callable by typing it — it's just tucked behind /admin's categorized
# menu instead of cluttering this list. See keyboards.py::ADMIN_CATEGORIES.
_BOT_COMMANDS = [
    BotCommand("start", "Show the welcome message and command list"),
    BotCommand("search", "Find the exact tradable symbol"),
    BotCommand("buy", "Place a buy order (confirmed)"),
    BotCommand("sell", "Place a sell order (confirmed)"),
    BotCommand("positions", "Show open positions"),
    BotCommand("orders", "Show today's order book"),
    BotCommand("env", "Edit environment variables"),
    BotCommand("admin", "Browse admin/ops commands by category"),
    BotCommand("cancel", "Cancel active operation"),
    BotCommand("help", "Show the full command list"),
]


async def _warm_instrument_cache() -> None:
    """Pre-fetch the equity + fno instrument masters so the FIRST /search or
    /buy of the day doesn't pay the full CSV download (previously the
    dominant cost of a "slow" search — see src/brokers/indmoney.py's
    process-wide TTL cache). Runs once at startup; failures are logged and
    swallowed since /search/resolve still work, just slower, on cache miss.
    """
    try:
        from src.brokers.factory import get_broker_adapter
        await get_broker_adapter("indmoney").warm_instrument_cache()
        logger.info("Instrument cache pre-warmed (equity + fno).")
    except Exception as exc:
        logger.warning("Instrument cache warm-up failed (will lazy-load on first search): %s", exc)


async def _post_init(application: Application) -> None:
    await application.bot.set_my_commands(_BOT_COMMANDS)
    # Fire-and-forget so bot startup isn't blocked by the instrument download.
    asyncio.create_task(_warm_instrument_cache())


def main() -> None:
    """Initializes and runs the Telegram Admin bot."""
    if not BOT_TOKEN:
        logger.error(
            "TELEGRAM_ADMIN_BOT_TOKEN is not set in environment or in the .env file. "
            "Please configure the token before running this bot."
        )
        return

    # Build the telegram application
    application = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()

    # Add the conversation handler for /env command
    application.add_handler(env_conversation_handler)

    # Trading command handlers (Phase 23 — order placement)
    application.add_handler(CommandHandler("buy", buy_command))
    application.add_handler(CommandHandler("sell", sell_command))
    application.add_handler(CallbackQueryHandler(order_confirm_callback, pattern="^order_confirm:"))
    application.add_handler(CommandHandler("positions", positions_command))
    application.add_handler(CommandHandler("orders", orders_command))
    application.add_handler(CommandHandler("search", search_command))

    # Add other administrative command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CallbackQueryHandler(admin_menu_callback, pattern="^admin_menu:"))
    application.add_handler(CallbackQueryHandler(admin_cmd_callback, pattern="^admin_cmd:"))
    application.add_handler(CommandHandler("restart", restart_command))
    application.add_handler(CallbackQueryHandler(cmd_restart_callback, pattern="^cmd_restart:"))
    application.add_handler(CommandHandler("show", show_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("health", health_command))
    application.add_handler(CommandHandler("tail", tail_command))
    application.add_handler(CommandHandler("logs", logs_command))
    application.add_handler(CommandHandler("backup", backup_command))
    application.add_handler(CommandHandler("backup_env", backup_env_command))
    application.add_handler(CallbackQueryHandler(backup_env_callback, pattern="^backup_env:"))
    application.add_handler(CommandHandler("reload", reload_command))
    application.add_handler(CommandHandler("disk", disk_command))
    application.add_handler(CommandHandler("uptime", uptime_command))
    application.add_handler(CommandHandler("ip", ip_command))
    application.add_handler(CommandHandler("cancel", cancel_command))

    logger.info("Starting Telegram Admin bot...")
    application.run_polling()

if __name__ == "__main__":
    # Configure logging if running this script directly
    log_level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=log_level
    )
    
    main()
