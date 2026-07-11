"""Tests for src/telegram_admin/main.py — bot command registration.

Confirms the native Telegram "/" autocomplete menu (_BOT_COMMANDS, set via
set_my_commands in _post_init) stays in sync with the CommandHandlers
actually registered in main() — a command present in one but not the other
is a real UX bug (shown in the menu but not wired, or wired but invisible).
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


class TestBotCommandsInSync:
    def test_every_registered_handler_is_in_the_command_menu(self):
        registered = _registered_command_names()
        listed = _bot_command_names()
        missing = registered - listed
        assert not missing, f"CommandHandlers not in the /-menu: {missing}"

    def test_every_menu_entry_has_a_registered_handler(self):
        registered = _registered_command_names()
        listed = _bot_command_names()
        stale = listed - registered
        assert not stale, f"/-menu entries with no CommandHandler: {stale}"

    def test_command_descriptions_are_non_empty(self):
        from src.telegram_admin.main import _BOT_COMMANDS
        for cmd in _BOT_COMMANDS:
            assert cmd.description, f"/{cmd.command} has an empty description"
