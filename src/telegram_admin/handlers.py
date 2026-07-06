import logging
import time
import tarfile
import shutil
import os
import subprocess
from datetime import datetime
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes
from src.telegram_admin.auth import admin_only
from src.telegram_admin.config import ALLOWED_VARIABLES, ENV_FILE_PATH, SERVICE_NAME, reload_config
import src.telegram_admin.env_manager as env_manager
import src.telegram_admin.service_manager as service_manager
from src.telegram_admin.keyboards import get_cmd_restart_keyboard, get_backup_env_keyboard
from src.telegram_admin.utils import split_message

logger = logging.getLogger(__name__)

@admin_only
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Replies to the /start command with the welcome message and available commands."""
    try:
        msg = (
            "✅ Zerodha MCP Admin Bot\n\n"
            "Available commands:\n\n"
            "/env         - Edit environment variables\n"
            "/show        - Show current variables (secrets masked)\n"
            "/status      - Get structured service status\n"
            "/health      - Run systemctl & HTTP API health check\n"
            "/restart     - Restart zerodha-mcp service\n"
            "/reload      - Re-read .env file configurations\n"
            "/tail [N]    - View last N logs (default 20)\n"
            "/logs        - View last 20 logs (shortcut)\n"
            "/backup      - Create a safe backup (excludes secrets)\n"
            "/backup_env  - Create a sensitive backup of .env file\n"
            "/disk        - Check disk, RAM, CPU load info\n"
            "/uptime      - Check Oracle VM and service uptimes\n"
            "/ip          - Get public and private IPs\n"
            "/cancel      - Cancel active operation"
        )
        await update.message.reply_text(msg)
    except Exception as exc:
        logger.error("Error in start_command: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Error: {exc}")

@admin_only
async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompts for confirmation before restarting the service."""
    try:
        reply_markup = get_cmd_restart_keyboard()
        await update.message.reply_text(
            "Restart zerodha-mcp?",
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
            await query.message.edit_text("♻️ Restarting zerodha-mcp service...")
            
            start_time = time.perf_counter()
            service_manager.restart_service()
            duration = time.perf_counter() - start_time
            
            is_active = service_manager.is_service_active()
            if is_active:
                await query.message.reply_text(
                    f"🟢 Service restarted successfully.\n"
                    f"✔ Completed in {duration:.1f} s"
                )
            else:
                await query.message.reply_text("🔴 Restart failed.")
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
            elif any(secret in var.upper() for secret in ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH")):
                display_val = "*************"
            else:
                display_val = val
            lines.append(f"{var:<25} {display_val}")
        
        await update.message.reply_text(
            f"```\n" + "\n".join(lines) + "\n```",
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
        import urllib.request
        import json
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
