from telegram import InlineKeyboardButton, InlineKeyboardMarkup

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
