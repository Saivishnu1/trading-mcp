import logging
import shutil
import subprocess
import tarfile
import time
from datetime import datetime
from pathlib import Path

from telegram import ForceReply, Update
from telegram.ext import ContextTypes

import src.telegram_admin.env_manager as env_manager
import src.telegram_admin.service_manager as service_manager
from src.telegram_admin.auth import admin_only
from src.telegram_admin.config import ALLOWED_VARIABLES, ENV_FILE_PATH, SERVICE_NAME, reload_config
from src.telegram_admin.keyboards import (
    ADMIN_CATEGORIES,
    get_admin_category_keyboard,
    get_admin_menu_keyboard,
    get_backup_env_keyboard,
    get_cmd_restart_keyboard,
    get_order_confirm_keyboard,
)
from src.telegram_admin.order_parser import ParseError, format_order_summary, parse_order_args
from src.telegram_admin.utils import split_message

logger = logging.getLogger(__name__)

_COMMAND_LIST_MESSAGE = (
    "✅ Zerodha MCP Admin Bot\n\n"
    "📈 Trading:\n\n"
    "/search TEXT - Find the exact tradable symbol (do this first!)\n"
    "/buy SYM QTY [MARKET|LIMIT price] - Place a buy order (confirmed)\n"
    "/sell SYM QTY [MARKET|LIMIT price] - Place a sell order (confirmed)\n"
    "/positions   - Show open positions\n"
    "/orders      - Show today's order book\n\n"
    "🛠 Admin:\n\n"
    "/env         - Edit environment variables\n"
    "/admin       - Browse admin/ops commands by category\n"
    "/cancel      - Cancel active operation\n"
    "/help        - Show this command list\n\n"
    "Tip: /admin groups the rarely-used commands (status, health, restart, "
    "logs, backups, config) into a tappable menu instead of listing all of "
    "them here."
)


@admin_only
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Replies to the /start command with the welcome message and available commands."""
    try:
        await update.message.reply_text(_COMMAND_LIST_MESSAGE)
    except Exception as exc:
        logger.error("Error in start_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error: {exc}")


@admin_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Replies to /help with the same command list as /start — for when you
    forget what the bot can do mid-session, without re-triggering /start's
    welcome framing."""
    try:
        await update.message.reply_text(_COMMAND_LIST_MESSAGE)
    except Exception as exc:
        logger.error("Error in help_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error: {exc}")

@admin_only
async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompts for confirmation before restarting the service."""
    try:
        reply_markup = get_cmd_restart_keyboard()
        await update.message.reply_text(
            "Restart zerodha-mcp and zerodha-monitor?",
            reply_markup=reply_markup
        )
    except Exception as exc:
        logger.error("Error in restart_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error prompting for restart: {exc}")

@admin_only
async def cmd_restart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the callback for the /restart command confirmation."""
    query = update.callback_query
    await query.answer()

    try:
        data = query.data or ""
        if data == "cmd_restart:yes":
            await query.message.edit_text("♻️ Restarting zerodha-mcp and zerodha-monitor...")

            start_time = time.perf_counter()
            service_manager.restart_service()
            duration = time.perf_counter() - start_time

            active = service_manager.are_restart_services_active()
            status_lines = "\n".join(
                f"{'🟢' if ok else '🔴'} {name}" for name, ok in active.items()
            )
            await query.message.reply_text(
                f"{status_lines}\n"
                f"✔ Completed in {duration:.1f} s"
            )
        elif data == "cmd_restart:no":
            await query.message.edit_text("Restart cancelled.")
        else:
            logger.warning("Invalid callback data in cmd_restart_callback: %s", data)
            await query.message.reply_text("❌ Invalid selection.")
    except Exception as exc:
        logger.error("Error in cmd_restart_callback: %s", exc, exc_info=True)
        await query.message.reply_text(f"❌ Error during restart: {exc}")

@admin_only
async def show_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows allowed environment variables with secrets masked."""
    try:
        env_vars = env_manager.read_env(ENV_FILE_PATH)
        lines = []
        for var in ALLOWED_VARIABLES:
            val = env_vars.get(var)
            if val is None:
                display_val = "[not set]"
            # Automatically mask any secret variables based on keyword matching
            elif any(secret in var.upper() for secret in ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH", "PIN")):
                display_val = "*************"
            else:
                display_val = val
            lines.append(f"{var:<25} {display_val}")

        await update.message.reply_text(
            "```\n" + "\n".join(lines) + "\n```",
            parse_mode="Markdown"
        )
    except Exception as exc:
        logger.error("Error in show_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error displaying variables: {exc}")

@admin_only
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Replies with structured status information of the service."""
    try:
        status = service_manager.get_service_status()
        msg = (
            f"📊 **Service Status: {SERVICE_NAME}**\n\n"
            f"• **Active**: {status['active']}\n"
            f"• **PID**: `{status['pid']}`\n"
            f"• **Uptime**: {status['uptime']}\n"
            f"• **Memory**: `{status['memory']}`\n"
            f"• **Latest Log**: `{status['last_log']}`"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as exc:
        logger.error("Error in status_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error fetching status: {exc}")

@admin_only
async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Performs systemctl and HTTP API local health checks."""
    try:
        # Check systemd is-active
        is_active = service_manager.is_service_active()
        sysctl_status = "🟢 active (running)" if is_active else "🔴 inactive"

        # Check HTTP status
        import json
        import urllib.request
        try:
            # Short timeout of 2.0s for the local HTTP call
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2.0) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    if data.get("status") == "ok":
                        http_status = "🟢 OK (200)"
                    elif data.get("status") == "healthy":
                        http_status = "🟢 Healthy"
                    else:
                        http_status = f"🟡 Unexpected body: {data}"
                else:
                    http_status = f"🔴 Failed (status {response.status})"
        except Exception as http_exc:
            http_status = f"🔴 Failed: {http_exc}"

        msg = (
            f"● Service Health Status:\n"
            f"  • systemctl: {sysctl_status}\n"
            f"  • HTTP API: {http_status}"
        )
        await update.message.reply_text(msg)
    except Exception as exc:
        logger.error("Error in health_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error checking health: {exc}")

@admin_only
async def tail_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetches the last N logs (defaults to 20, up to 250)."""
    try:
        n = 20
        if context.args:
            try:
                n = int(context.args[0])
                if n <= 0 or n > 250:
                    await update.message.reply_text("Please specify a line count between 1 and 250.")
                    return
            except ValueError:
                await update.message.reply_text("Usage: /tail [number]")
                return

        logs = service_manager.get_service_logs(n)
        if not logs or not logs.strip():
            await update.message.reply_text("No logs found.")
            return

        # Split logs if they exceed character limits
        chunks = split_message(logs)
        for chunk in chunks:
            await update.message.reply_text(f"```log\n{chunk}\n```", parse_mode="Markdown")
    except Exception as exc:
        logger.error("Error in tail_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error tailing logs: {exc}")

@admin_only
async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetches the last 20 journal logs (shortcut to /tail 20)."""
    try:
        logs = service_manager.get_service_logs(20)
        if not logs or not logs.strip():
            await update.message.reply_text("No logs found.")
            return

        chunks = split_message(logs)
        for chunk in chunks:
            await update.message.reply_text(f"```log\n{chunk}\n```", parse_mode="Markdown")
    except Exception as exc:
        logger.error("Error in logs_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error fetching logs: {exc}")

@admin_only
async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Creates a timestamped SAFE backup archive (excludes secrets .env files)."""
    try:
        await update.message.reply_text("📦 Generating safe backup archive...")

        # Workspace directories
        workspace_dir = Path(".").resolve()

        # Create timestamp and names
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"zerodha_mcp_safe_backup_{timestamp}.tar.gz"

        # Create temp directory inside workspace
        temp_backup_dir = workspace_dir / f"safe_backup_temp_{timestamp}"
        temp_backup_dir.mkdir(exist_ok=True)

        # 1. Copy journal.db (Database)
        db_path = workspace_dir / "journal.db"
        if db_path.exists():
            shutil.copy2(db_path, temp_backup_dir / "journal.db")

        # 2. Copy systemd unit files
        sysd_dir = temp_backup_dir / "systemd"
        sysd_dir.mkdir(exist_ok=True)

        mcp_service = Path("/etc/systemd/system/zerodha-mcp.service")
        if mcp_service.exists():
            shutil.copy2(mcp_service, sysd_dir / "zerodha-mcp.service")

        admin_service = Path("/etc/systemd/system/telegram-admin.service")
        if admin_service.exists():
            shutil.copy2(admin_service, sysd_dir / "telegram-admin.service")

        # 3. Fetch last 200 logs and save to a file
        try:
            logs = service_manager.get_service_logs(200)
            (temp_backup_dir / "zerodha-mcp.log").write_text(logs, encoding="utf-8")
        except Exception as log_exc:
            logger.warning("Could not include logs in backup: %s", log_exc)

        # Create compressed tarball
        archive_path = workspace_dir / archive_name
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(temp_backup_dir, arcname="safe_backup")

        # Cleanup temp directory
        shutil.rmtree(temp_backup_dir)

        # Send document to Telegram
        with open(archive_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=archive_name,
                caption="✅ Safe backup completed successfully (excludes .env secrets)."
            )

        # Delete local archive after sending
        if archive_path.exists():
            archive_path.unlink()

    except Exception as exc:
        logger.error("Error in backup_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Backup failed: {exc}")
        # Attempt cleanup
        if 'temp_backup_dir' in locals() and temp_backup_dir.exists():
            shutil.rmtree(temp_backup_dir, ignore_errors=True)
        if 'archive_path' in locals() and archive_path.exists():
            archive_path.unlink(missing_ok=True)

@admin_only
async def backup_env_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompts for confirmation before backing up sensitive .env credentials."""
    try:
        reply_markup = get_backup_env_keyboard()
        await update.message.reply_text(
            "⚠️ This archive contains API keys and passwords.\n\n"
            "Continue to generate env backup?",
            reply_markup=reply_markup
        )
    except Exception as exc:
        logger.error("Error in backup_env_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error prompting for env backup: {exc}")

@admin_only
async def backup_env_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the callback confirmation query for backing up sensitive env variables."""
    query = update.callback_query
    await query.answer()

    try:
        data = query.data or ""
        if data == "backup_env:yes":
            await query.message.edit_text("🔒 Packaging credentials...")

            workspace_dir = Path(".").resolve()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_name = f"zerodha_mcp_secrets_{timestamp}.tar.gz"

            temp_backup_dir = workspace_dir / f"secrets_temp_{timestamp}"
            temp_backup_dir.mkdir(exist_ok=True)

            # Copy .env and .env.bak
            if ENV_FILE_PATH.exists():
                shutil.copy2(ENV_FILE_PATH, temp_backup_dir / ".env")
            bak_env = ENV_FILE_PATH.with_suffix(".env.bak")
            if bak_env.exists():
                shutil.copy2(bak_env, temp_backup_dir / ".env.bak")

            archive_path = workspace_dir / archive_name
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(temp_backup_dir, arcname="secrets_backup")

            shutil.rmtree(temp_backup_dir)

            with open(archive_path, "rb") as f:
                await query.message.reply_document(
                    document=f,
                    filename=archive_name,
                    caption="🔑 Sensitive credentials backup completed."
                )

            if archive_path.exists():
                archive_path.unlink()
        elif data == "backup_env:no":
            await query.message.edit_text("Secrets backup cancelled.")
        else:
            logger.warning("Invalid callback data in backup_env_callback: %s", data)
            await query.message.reply_text("❌ Invalid selection.")
    except Exception as exc:
        logger.error("Error in backup_env_callback: %s", exc, exc_info=True)
        await query.message.reply_text(f"❌ Error exporting secrets: {exc}")
        # Cleanup
        if 'temp_backup_dir' in locals() and temp_backup_dir.exists():
            shutil.rmtree(temp_backup_dir, ignore_errors=True)
        if 'archive_path' in locals() and archive_path.exists():
            archive_path.unlink(missing_ok=True)

@admin_only
async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reloads the cached bot configuration from the .env file without restart."""
    try:
        reload_config()
        await update.message.reply_text(
            "✅ Configurations reloaded successfully.\n"
            "• Checked Admin ID & Bot Token from /etc/zerodha-mcp/.env\n"
            "• Updates to ADMIN ID are applied instantly.\n"
            "• (Note: BOT_TOKEN changes will only take effect on service restart)"
        )
    except Exception as exc:
        logger.error("Error in reload_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error reloading config: {exc}")

@admin_only
async def disk_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Replies with system disk space, memory info, and load averages."""
    try:
        # Disk usage info (root directory /)
        try:
            df = subprocess.run(["df", "-h", "/"], check=True, text=True, capture_output=True).stdout.strip()
        except Exception as e:
            df = f"Error: {e}"

        # RAM info
        try:
            free = subprocess.run(["free", "-h"], check=True, text=True, capture_output=True).stdout.strip()
        except Exception as e:
            free = f"Error: {e}"

        # Load average info
        try:
            uptime_str = subprocess.run(["uptime"], check=True, text=True, capture_output=True).stdout.strip()
        except Exception as e:
            uptime_str = f"Error: {e}"

        msg = (
            "💿 **Disk Usage (Root /)**\n"
            f"```\n{df}\n```\n"
            "🧠 **RAM Memory**\n"
            f"```\n{free}\n```\n"
            "📈 **Load Average**\n"
            f"```\n{uptime_str}\n```"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as exc:
        logger.error("Error in disk_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error fetching system statistics: {exc}")

@admin_only
async def uptime_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Replies with the uptime of the Oracle VM and key systemd services."""
    try:
        # VM Uptime
        try:
            vm_up = subprocess.run(["uptime", "-p"], check=True, text=True, capture_output=True).stdout.strip()
        except Exception:
            try:
                vm_up = subprocess.run(["uptime"], check=True, text=True, capture_output=True).stdout.strip()
            except Exception as e:
                vm_up = f"Unknown ({e})"

        # Services uptime
        mcp_up = _get_service_uptime("zerodha-mcp")
        admin_up = _get_service_uptime("telegram-admin")

        msg = (
            "⏱️ **System Uptimes**\n\n"
            f"• **Oracle VM**:\n  {vm_up}\n\n"
            f"• **zerodha-mcp service**:\n  {mcp_up}\n\n"
            f"• **telegram-admin service**:\n  {admin_up}"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as exc:
        logger.error("Error in uptime_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error querying uptimes: {exc}")

def _get_service_uptime(service_name: str) -> str:
    """Retrieves service uptime from systemctl status."""
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "status", service_name],
            check=True, text=True, capture_output=True
        )
        for line in result.stdout.splitlines():
            line_stripped = line.strip()
            if "Active:" in line_stripped:
                if ";" in line_stripped:
                    return line_stripped.split(";", 1)[1].strip()
                return line_stripped.split("Active:", 1)[1].strip()
        return "Unknown"
    except Exception as exc:
        return f"Inactive / Error ({exc})"

@admin_only
async def ip_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Queries and returns the VM's public and private network IPs."""
    try:
        await update.message.reply_text("🌐 Resolving network IPs...")

        # Public IP
        public_ip = "Unknown"
        try:
            import urllib.request
            # Query standard public API
            with urllib.request.urlopen("https://api.ipify.org", timeout=3.0) as resp:
                public_ip = resp.read().decode().strip()
        except Exception as exc:
            public_ip = f"Error ({exc})"

        # Private IP
        private_ip = "Unknown"
        try:
            res = subprocess.run(["hostname", "-I"], check=True, text=True, capture_output=True)
            private_ip = res.stdout.strip()
        except Exception:
            try:
                import socket
                private_ip = socket.gethostbyname(socket.gethostname())
            except Exception as exc:
                private_ip = f"Error ({exc})"

        msg = (
            "🌐 **Network IP Addresses**\n\n"
            f"• **Public IP**: `{public_ip}`\n"
            f"• **Private IP**: `{private_ip}`"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as exc:
        logger.error("Error in ip_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error fetching network IPs: {exc}")

@admin_only
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clears any pending variable selection stored in user_data outside of /env flow."""
    try:
        context.user_data.clear()
        await update.message.reply_text("Cancelled.")
    except Exception as exc:
        logger.error("Error in cancel_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error cancelling: {exc}")


# ---------------------------------------------------------------------------
# /admin menu — categorized navigation over the rarely-used admin/ops
# commands (status, health, restart, logs, backups, config), so the native
# "/" picker only needs the daily-trading commands + /admin + /help instead
# of a flat 21-command list. Pure navigation: every leaf button replies with
# the exact command to type rather than running anything itself, so this
# never touches any existing handler's behavior.
# ---------------------------------------------------------------------------

@admin_only
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the top-level /admin category menu."""
    try:
        await update.message.reply_text(
            "🛠 Admin menu — pick a category:",
            reply_markup=get_admin_menu_keyboard(),
        )
    except Exception as exc:
        logger.error("Error in admin_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error: {exc}")


@admin_only
async def admin_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles category selection: admin_menu:<category> or admin_menu:_root."""
    query = update.callback_query
    await query.answer()
    try:
        category_key = (query.data or "").split(":", 1)[1]
        if category_key == "_root":
            await query.message.edit_text(
                "🛠 Admin menu — pick a category:",
                reply_markup=get_admin_menu_keyboard(),
            )
            return
        if category_key not in ADMIN_CATEGORIES:
            await query.message.edit_text("❌ Unknown category.")
            return
        category = ADMIN_CATEGORIES[category_key]
        await query.message.edit_text(
            f"{category['label']} — pick a command:",
            reply_markup=get_admin_category_keyboard(category_key),
        )
    except Exception as exc:
        logger.error("Error in admin_menu_callback: %s", exc, exc_info=True)
        await query.message.reply_text(f"❌ Error: {exc}")


@admin_only
async def admin_cmd_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles a leaf command selection: admin_cmd:<command>. Replies with
    the exact command to type/tap rather than running it directly — keeps
    every existing handler's behavior untouched (see module docstring)."""
    query = update.callback_query
    await query.answer()
    try:
        command = (query.data or "").split(":", 1)[1]
        await query.message.reply_text(
            f"Type: {command}",
            reply_markup=ForceReply(selective=True, input_field_placeholder=command),
        )
    except Exception as exc:
        logger.error("Error in admin_cmd_callback: %s", exc, exc_info=True)
        await query.message.reply_text(f"❌ Error: {exc}")


# ---------------------------------------------------------------------------
# Trading commands — /buy, /sell, order confirmation, /positions, /orders
# ---------------------------------------------------------------------------

async def _handle_order_command(update: Update, context: ContextTypes.DEFAULT_TYPE, side: str) -> None:
    """Shared body for /buy and /sell: parse args, resolve security_id, and
    prompt for YES/NO confirmation. The order is only placed on confirmation."""
    parsed = parse_order_args(context.args or [], side)
    if isinstance(parsed, ParseError):
        if not context.args:
            # Bare tap from the "/" picker (no args at all) — ForceReply
            # makes it obvious typing is expected, not another tap
            # (2026-07-11, see search_command for the same reasoning).
            await update.message.reply_text(
                parsed.message,
                reply_markup=ForceReply(selective=True, input_field_placeholder="RELIANCE 1 LIMIT 2870"),
            )
        else:
            await update.message.reply_text(parsed.message)
        return

    # Resolve the trading symbol → INDstocks security_id before confirming, so a
    # bad symbol fails fast (before the user taps PLACE).
    from src.execution.service import resolve_symbol
    try:
        sec_id = await resolve_symbol(
            parsed.symbol, exchange=parsed.exchange, segment=parsed.segment
        )
    except Exception as exc:
        logger.error("security_id resolution error: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Could not resolve '{parsed.symbol}': {exc}")
        return
    if not sec_id:
        await update.message.reply_text(
            f"❌ Symbol '{parsed.symbol}' not found in the {parsed.exchange} "
            f"{parsed.segment} instrument list. Check the exact trading symbol."
        )
        return
    parsed.security_id = sec_id

    context.user_data["pending_order"] = parsed
    await update.message.reply_text(
        format_order_summary(parsed),
        reply_markup=get_order_confirm_keyboard(),
        parse_mode="Markdown",
    )


@admin_only
async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/buy SYMBOL QTY [MARKET|LIMIT price] [product] [exchange] — confirm then place."""
    try:
        await _handle_order_command(update, context, "BUY")
    except Exception as exc:
        logger.error("Error in buy_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error: {exc}")


@admin_only
async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/sell SYMBOL QTY [MARKET|LIMIT price] [product] [exchange] — confirm then place."""
    try:
        await _handle_order_command(update, context, "SELL")
    except Exception as exc:
        logger.error("Error in sell_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error: {exc}")


@admin_only
async def order_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the YES/NO confirmation for a pending /buy or /sell order."""
    query = update.callback_query
    await query.answer()
    try:
        data = query.data or ""
        if data == "order_confirm:no":
            context.user_data.pop("pending_order", None)
            await query.message.edit_text("Order cancelled.")
            return
        if data != "order_confirm:yes":
            logger.warning("Invalid callback data in order_confirm_callback: %s", data)
            await query.message.reply_text("❌ Invalid selection.")
            return

        req = context.user_data.pop("pending_order", None)
        if req is None:
            await query.message.edit_text("⚠️ No pending order (it may have expired). Send /buy or /sell again.")
            return

        await query.message.edit_text("⏳ Placing order...")
        from src.execution.service import submit_order
        user_id = str(update.effective_user.id) if update.effective_user else None
        result = await submit_order(req, source="telegram", user_id=user_id)

        if result.get("status") == "ok":
            lines = [
                "✅ Order placed",
                f"• {req.transaction_type} {req.symbol} x{req.quantity}",
                f"• Order ID: `{result.get('order_id')}`",
                f"• Status: {result.get('order_status') or 'submitted'}",
            ]
            if result.get("child_order_id"):
                lines.append(f"• SL/Target leg: `{result['child_order_id']}` ({result.get('child_order_status') or 'pending'})")
            if req.trailing_sl_points is not None:
                lines.append(f"• Trailing SL active: {req.trailing_sl_points:g} points (bot-managed)")
            await query.message.reply_text("\n".join(lines), parse_mode="Markdown")
        else:
            detail = result.get("message") or result.get("body") or result.get("order_status") or "unknown error"
            await query.message.reply_text(f"❌ Order rejected: {detail}")
    except Exception as exc:
        logger.error("Error in order_confirm_callback: %s", exc, exc_info=True)
        await query.message.reply_text(f"❌ Error placing order: {exc}")


@admin_only
async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/positions — show open INDmoney positions (read-only, for quick reference)."""
    try:
        from src.brokers.factory import get_broker_adapter
        positions = await get_broker_adapter("indmoney").get_positions()
        if not positions:
            await update.message.reply_text("No open positions.")
            return
        lines = ["📈 *Positions*"]
        for p in positions:
            sign = "🟢" if p.pnl >= 0 else "🔴"
            lines.append(f"{sign} {p.symbol} x{p.quantity} @ ₹{p.avg_price:g} → ₹{p.current_price:g} (P&L ₹{p.pnl:g})")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as exc:
        logger.error("Error in positions_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error fetching positions: {exc}")


@admin_only
async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/orders — show today's order book (read-only)."""
    try:
        from src.brokers.factory import get_broker_adapter
        orders = await get_broker_adapter("indmoney").get_orders()
        if not orders:
            await update.message.reply_text("No orders today.")
            return
        lines = ["🧾 *Order book*"]
        for o in orders:
            lines.append(f"• {o.transaction_type} {o.symbol} x{o.quantity} @ ₹{o.price:g} — {o.status}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as exc:
        logger.error("Error in orders_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error fetching orders: {exc}")


@admin_only
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/search TEXT — look up exact tradable symbols before /buy or /sell.

    Solves "what's the exact symbol name" — /buy and /sell need an exact
    trading symbol, so this lets you type a partial name (e.g. "reliance" or
    "nifty 24200") and see the real symbols to copy into the order command.
    """
    try:
        query = " ".join(context.args or []).strip()
        if len(query) < 2:
            # ForceReply pops the client's keyboard open with focus on this
            # message — the clearest signal that typing (not tapping) is
            # what's needed here (2026-07-11: tapping /search from the "/"
            # picker sends it bare immediately, no way to add text after).
            await update.message.reply_text(
                "Usage: /search TEXT (at least 2 characters)\ne.g. /search reliance",
                reply_markup=ForceReply(selective=True, input_field_placeholder="reliance"),
            )
            return
        from src.execution.service import search_symbols
        results = await search_symbols(query)
        if not results:
            await update.message.reply_text(f"No symbols found matching '{query}'.")
            return
        lines = [f"🔎 *Symbols matching '{query}'*"]
        seen_symbols: dict[str, int] = {}
        for r in results:
            seen_symbols[r["symbol"]] = seen_symbols.get(r["symbol"], 0) + 1
        for r in results:
            tag = "📈" if r["segment"] == "DERIVATIVE" else "📊"
            expiry = f"  exp {r['expiry'][:10]}" if r.get("expiry") else ""
            lines.append(f"{tag} `{r['symbol']}`  —  {r['name']}  ({r['exchange']}){expiry}")
        # Index options (NIFTY/SENSEX still run a weekly series) can list several
        # rows under one display symbol, one per weekly expiry that month — /buy
        # and /sell can only key off the typed symbol text, so ordering one of
        # these by name alone is ambiguous (INDstocks returns whichever weekly
        # contract the CSV lists first). Surface that up front rather than let
        # the wrong expiry get bought silently.
        ambiguous = sorted({sym for sym, count in seen_symbols.items() if count > 1})
        if ambiguous:
            lines.append(
                "\n⚠️ " + ", ".join(f"`{s}`" for s in ambiguous) +
                " — matches multiple expiries above. /buy or /sell by this name "
                "may pick the WRONG one; use the web /trade page and pick the "
                "exact expiry from its dropdown instead for these."
            )
        lines.append("\nTap-copy a symbol, then /buy SYMBOL QTY or /sell SYMBOL QTY.")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as exc:
        logger.error("Error in search_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error searching symbols: {exc}")
