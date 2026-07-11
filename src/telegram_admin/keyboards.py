from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# /admin menu structure — grouped so the native "/" picker only needs to
# carry the 6-7 daily-trading commands + /admin + /help, instead of all 21
# commands flat. Each category button drills into its own submenu; each
# leaf button replies with the exact command to type (see
# handlers.py::admin_menu_callback) rather than running anything directly
# — a pure navigation aid, zero behavior change to any existing command.
ADMIN_CATEGORIES: dict[str, dict] = {
    "service": {
        "label": "⚙️ Service",
        "commands": [
            ("/status", "Service status"),
            ("/health", "Health check"),
            ("/restart", "Restart services"),
            ("/reload", "Reload .env config"),
            ("/uptime", "Uptimes"),
        ],
    },
    "logs": {
        "label": "📋 Logs",
        "commands": [
            ("/logs", "Last 20 logs"),
            ("/tail", "Tail N logs"),
        ],
    },
    "backups": {
        "label": "💾 Backups",
        "commands": [
            ("/backup", "Safe backup (no secrets)"),
            ("/backup_env", "Backup .env (sensitive)"),
        ],
    },
    "config": {
        "label": "🔧 Config",
        "commands": [
            # /env lives in the top-level "/" picker (daily-use), not here —
            # avoid listing it in two places.
            ("/show", "Show variables (masked)"),
            ("/ip", "Network IPs"),
            ("/disk", "Disk / RAM / load"),
        ],
    },
}


def get_admin_menu_keyboard() -> InlineKeyboardMarkup:
    """Top-level /admin menu — one button per category."""
    keyboard = [
        [InlineKeyboardButton(text=cat["label"], callback_data=f"admin_menu:{key}")]
        for key, cat in ADMIN_CATEGORIES.items()
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_category_keyboard(category_key: str) -> InlineKeyboardMarkup:
    """Submenu for one /admin category — one button per command, plus Back."""
    category = ADMIN_CATEGORIES[category_key]
    keyboard = [
        [InlineKeyboardButton(text=f"{cmd}  —  {desc}", callback_data=f"admin_cmd:{cmd}")]
        for cmd, desc in category["commands"]
    ]
    keyboard.append([InlineKeyboardButton(text="« Back", callback_data="admin_menu:_root")])
    return InlineKeyboardMarkup(keyboard)


def get_env_keyboard(allowed_variables: list[str]) -> InlineKeyboardMarkup:
    """Generates an inline keyboard with one button per allowed variable."""
    keyboard = []
    for var in allowed_variables:
        keyboard.append([InlineKeyboardButton(text=var, callback_data=f"edit_env:{var}")])
    return InlineKeyboardMarkup(keyboard)

def get_restart_keyboard() -> InlineKeyboardMarkup:
    """Generates an inline keyboard for confirming a service restart (YES/NO)."""
    keyboard = [
        [
            InlineKeyboardButton(text="YES", callback_data="restart:yes"),
            InlineKeyboardButton(text="NO", callback_data="restart:no")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_cmd_restart_keyboard() -> InlineKeyboardMarkup:
    """Generates an inline keyboard for confirming the /restart command (YES/NO)."""
    keyboard = [
        [
            InlineKeyboardButton(text="YES", callback_data="cmd_restart:yes"),
            InlineKeyboardButton(text="NO", callback_data="cmd_restart:no")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_backup_env_keyboard() -> InlineKeyboardMarkup:
    """Generates an inline keyboard for confirming environment backups (YES/NO)."""
    keyboard = [
        [
            InlineKeyboardButton(text="YES", callback_data="backup_env:yes"),
            InlineKeyboardButton(text="NO", callback_data="backup_env:no")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_order_confirm_keyboard() -> InlineKeyboardMarkup:
    """Generates a YES/NO keyboard to confirm placing a live order."""
    keyboard = [
        [
            InlineKeyboardButton(text="✅ PLACE", callback_data="order_confirm:yes"),
            InlineKeyboardButton(text="✖ CANCEL", callback_data="order_confirm:no")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)
