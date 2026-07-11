import logging
import os
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from src.telegram_admin.config import BOT_TOKEN
from src.telegram_admin.handlers import (
    start_command,
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
)
from src.telegram_admin.conversation import env_conversation_handler

logger = logging.getLogger(__name__)

def main() -> None:
    """Initializes and runs the Telegram Admin bot."""
    if not BOT_TOKEN:
        logger.error(
            "TELEGRAM_ADMIN_BOT_TOKEN is not set in environment or in the .env file. "
            "Please configure the token before running this bot."
        )
        return

    # Build the telegram application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add the conversation handler for /env command
    application.add_handler(env_conversation_handler)

    # Trading command handlers (Phase 23 — order placement)
    application.add_handler(CommandHandler("buy", buy_command))
    application.add_handler(CommandHandler("sell", sell_command))
    application.add_handler(CallbackQueryHandler(order_confirm_callback, pattern="^order_confirm:"))
    application.add_handler(CommandHandler("positions", positions_command))
    application.add_handler(CommandHandler("orders", orders_command))

    # Add other administrative command handlers
    application.add_handler(CommandHandler("start", start_command))
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
