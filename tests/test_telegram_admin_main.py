"""Tests for src/telegram_admin/main.py — bot command registration.

The native "/" menu (_BOT_COMMANDS) deliberately does NOT list every
registered command — only the daily-trading ones plus /admin, /help,
/cancel. Rarely-used admin/ops commands (status, health, restart, logs,
backups, config) are still fully registered and callable, just tucked
behind /admin's categorized submenu (keyboards.py::ADMIN_CATEGORIES)
instead of cluttering the flat picker.

What must stay true:
  - every _BOT_COMMANDS entry has a real CommandHandler (no dead menu button)
  - every command referenced inside ADMIN_CATEGORIES has a real
    CommandHandler (no dead /admin submenu button)
  - every command description is non-empty
"""
from __future__ import annotations

import ast
from pathlib import Path

_TELEGRAM_ADMIN_DIR = Path(__file__).parent.parent / "src" / "telegram_admin"
_MAIN_PY = _TELEGRAM_ADMIN_DIR / "main.py"
# /env is a CommandHandler entry_point nested inside conversation.py's
# ConversationHandler, not a plain top-level registration in main.py —
# scan both files rather than assume every command lives in main.py.
_CONVERSATION_PY = _TELEGRAM_ADMIN_DIR / "conversation.py"


def _registered_command_names() -> set[str]:
    """Parse main.py and conversation.py for every CommandHandler("name", ...)
    call — static analysis instead of importing+running main(), since main()
    builds a real Application and calls run_polling()."""
    names = set()
    for path in (_MAIN_PY, _CONVERSATION_PY):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "CommandHandler"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                names.add(node.args[0].value)
    return names


def _bot_command_names() -> set[str]:
    from src.telegram_admin.main import _BOT_COMMANDS
    return {c.command for c in _BOT_COMMANDS}


def _admin_menu_command_names() -> set[str]:
    """Every command referenced by ADMIN_CATEGORIES's leaf buttons, with the
    leading '/' stripped to match CommandHandler's bare names."""
    from src.telegram_admin.keyboards import ADMIN_CATEGORIES
    names = set()
    for category in ADMIN_CATEGORIES.values():
        for cmd, _desc in category["commands"]:
            names.add(cmd.lstrip("/").split()[0])
    return names


class TestBotCommandsInSync:
    def test_every_menu_entry_has_a_registered_handler(self):
        registered = _registered_command_names()
        listed = _bot_command_names()
        stale = listed - registered
        assert not stale, f"/-menu entries with no CommandHandler: {stale}"

    def test_command_descriptions_are_non_empty(self):
        from src.telegram_admin.main import _BOT_COMMANDS
        for cmd in _BOT_COMMANDS:
            assert cmd.description, f"/{cmd.command} has an empty description"

    def test_admin_submenu_commands_all_have_registered_handlers(self):
        registered = _registered_command_names()
        submenu = _admin_menu_command_names()
        stale = submenu - registered
        assert not stale, f"/admin submenu references commands with no handler: {stale}"

    def test_daily_trading_commands_are_in_the_flat_menu(self):
        """The core trading loop must stay one tap away — never buried
        behind /admin's submenu."""
        listed = _bot_command_names()
        for cmd in ("search", "buy", "sell", "positions", "orders"):
            assert cmd in listed, f"/{cmd} missing from the daily-use / menu"

    def test_admin_and_help_are_in_the_flat_menu(self):
        listed = _bot_command_names()
        assert "admin" in listed
        assert "help" in listed
