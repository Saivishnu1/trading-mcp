import os
from pathlib import Path
from dotenv import load_dotenv

ENV_FILE_PATH = Path("/etc/zerodha-mcp/.env")
SERVICE_NAME = "zerodha-mcp"

# Services restarted together after an env var update — both zerodha-mcp and
# zerodha-monitor read the same ENV_FILE_PATH, so a shared var (e.g.
# INDSTOCKS_TOKEN) must reach both processes or the monitor keeps running on
# the stale value until someone restarts it by hand.
RESTART_SERVICES = ["zerodha-mcp", "zerodha-monitor"]

# Whitelist of editable variables via Telegram bot
ALLOWED_VARIABLES = [
    "INDSTOCKS_TOKEN",
    "TRADE_PIN",
    "KITE_ACCESS_TOKEN",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "PUBLIC_URL",
    "BROKER_BACKEND",
    "LOG_LEVEL",
    "PCR_SHIFT_THRESHOLD",
    "VIX_SPIKE_THRESHOLD",
    "PROFIT_ALERT_PCT",
    "DEFAULT_CALLMEBOT_API_KEY",
    "DEFAULT_TELEGRAM_BOT_TOKEN",
    "DEFAULT_TELEGRAM_CHAT_ID",
    "OILPRICEAPI_KEY",
]

# Global variables updated by reload_config
ADMIN_ID = 1344481918
BOT_TOKEN = ""

def reload_config() -> None:
    """Reloads environment variables from the dotenv file and updates config values."""
    global ADMIN_ID, BOT_TOKEN
    
    if ENV_FILE_PATH.exists():
        load_dotenv(ENV_FILE_PATH, override=True)
    else:
        load_dotenv(override=True)
        
    try:
        ADMIN_ID = int(os.environ.get("TELEGRAM_ADMIN_ID", "1344481918"))
    except ValueError:
        ADMIN_ID = 1344481918
        
    BOT_TOKEN = os.environ.get("TELEGRAM_ADMIN_BOT_TOKEN", "")

# Perform initial load of config values
reload_config()
