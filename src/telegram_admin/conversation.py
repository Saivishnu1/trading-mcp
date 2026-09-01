import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import src.telegram_admin.service_manager as service_manager
from src.telegram_admin.auth import admin_only
from src.telegram_admin.config import ALLOWED_VARIABLES, ENV_FILE_PATH
from src.telegram_admin.env_manager import update_variable
from src.telegram_admin.keyboards import get_env_keyboard, get_restart_keyboard

logger = logging.getLogger(__name__)

# Conversation states
AWAITING_VARIABLE_SELECTION, AWAITING_VALUE, AWAITING_RESTART_CONFIRMATION = range(3)

@admin_only
async def env_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for /env command. Shows available variables."""
    try:
        reply_markup = get_env_keyboard(ALLOWED_VARIABLES)
        await update.message.reply_text(
            "✅ Zerodha MCP Environment Variables\n\n"
            "Select an environment variable to modify:",
            reply_markup=reply_markup
        )
        return AWAITING_VARIABLE_SELECTION
    except Exception as exc:
        logger.error("Error in env_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error displaying environment variables: {exc}")
        return ConversationHandler.END

@admin_only
async def select_variable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback query handler when a variable button is clicked."""
    query = update.callback_query
    await query.answer()

    try:
        data = query.data or ""
        if not data.startswith("edit_env:"):
            logger.warning("Invalid callback data in select_variable: %s", data)
            await query.message.reply_text("❌ Invalid variable selection.")
            return ConversationHandler.END

        var_name = data.split(":", 1)[1]
        if var_name not in ALLOWED_VARIABLES:
            logger.warning("Attempted to edit non-allowed variable: %s", var_name)
            await query.message.reply_text("❌ Modifying that variable is not permitted.")
            return ConversationHandler.END

        context.user_data["selected_var"] = var_name

        await query.message.edit_text(
            f"Selected:\n\n"
            f"`{var_name}`\n\n"
            f"Send the new value.",
            parse_mode="Markdown"
        )
        return AWAITING_VALUE
    except Exception as exc:
        logger.error("Error in select_variable: %s", exc, exc_info=True)
        await query.message.reply_text(f"❌ Error selecting variable: {exc}")
        return ConversationHandler.END

@admin_only
async def receive_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the value for the selected variable and updates the .env file."""
    try:
        new_value = update.message.text
        var_name = context.user_data.get("selected_var")

        if not var_name or var_name not in ALLOWED_VARIABLES:
            logger.warning("receive_value called without a valid selected variable in context")
            await update.message.reply_text("❌ No variable selected. Please restart the process with /env.")
            return ConversationHandler.END

        # Update in the .env file
        update_variable(ENV_FILE_PATH, var_name, new_value)

        reply_markup = get_restart_keyboard()
        await update.message.reply_text(
            f"✅ `{var_name}` updated.\n\n"
            f"Restart zerodha-mcp and zerodha-monitor now?",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return AWAITING_RESTART_CONFIRMATION
    except Exception as exc:
        logger.error("Error in receive_value: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error updating variable: {exc}")
        return ConversationHandler.END

@admin_only
async def confirm_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback query handler for the restart confirmation YES/NO buttons."""
    query = update.callback_query
    await query.answer()

    try:
        data = query.data or ""
        if data == "restart:yes":
            await query.message.edit_text("♻️ Restarting zerodha-mcp and zerodha-monitor...")

            import time
            start_time = time.perf_counter()
            # Restart both services — env vars like INDSTOCKS_TOKEN are read
            # by both processes, not just zerodha-mcp.
            service_manager.restart_service()
            duration = time.perf_counter() - start_time

            active = service_manager.are_restart_services_active()
            status_lines = "\n".join(
                f"  {'🟢' if ok else '🔴'} {name}" for name, ok in active.items()
            )
            all_ok = all(active.values())

            await query.message.reply_text(
                f"{'♻️ Restart successful.' if all_ok else '⚠️ Restart completed with issues.'}\n"
                f"✔ Completed in {duration:.1f} s\n\n"
                f"{status_lines}",
                parse_mode="Markdown"
            )
        elif data == "restart:no":
            await query.message.edit_text(
                "Changes saved.\n\n"
                "Restart later using /restart."
            )
        else:
            logger.warning("Invalid callback data in confirm_restart: %s", data)
            await query.message.reply_text("❌ Invalid selection.")

        context.user_data.clear()
        return ConversationHandler.END
    except Exception as exc:
        logger.error("Error in confirm_restart: %s", exc, exc_info=True)
        await query.message.reply_text(f"❌ Error restarting service: {exc}")
        context.user_data.clear()
        return ConversationHandler.END

@admin_only
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the active conversation and clears context user data."""
    try:
        context.user_data.clear()
        await update.message.reply_text("Cancelled.")
        return ConversationHandler.END
    except Exception as exc:
        logger.error("Error in cancel_conversation: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error cancelling: {exc}")
        return ConversationHandler.END

# Construct the ConversationHandler
env_conversation_handler = ConversationHandler(
    entry_points=[CommandHandler("env", env_command)],
    states={
        AWAITING_VARIABLE_SELECTION: [
            CallbackQueryHandler(select_variable, pattern="^edit_env:")
        ],
        AWAITING_VALUE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_value)
        ],
        AWAITING_RESTART_CONFIRMATION: [
            CallbackQueryHandler(confirm_restart, pattern="^restart:")
        ]
    },
    fallbacks=[CommandHandler("cancel", cancel_conversation)],
    allow_reentry=True
)
