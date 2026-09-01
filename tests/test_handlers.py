from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Message, Update, User
from telegram.ext import ContextTypes

from src.telegram_admin.handlers import (
    admin_cmd_callback,
    admin_command,
    admin_menu_callback,
    buy_command,
    help_command,
    order_confirm_callback,
    search_command,
    start_command,
    status_command,
)

ADMIN_ID = 1344481918


@pytest.mark.anyio
async def test_help_command_lists_daily_commands_and_points_to_admin():
    """/help shows the daily-trading commands directly, plus /admin as the
    entry point for everything else (2026-07-11: the old flat 21-command
    dump was too much to scan — rarely-used ops commands now live behind
    /admin's categorized menu instead, see keyboards.py::ADMIN_CATEGORIES)."""
    update = MagicMock(spec=Update)
    message = AsyncMock(spec=Message)
    user = MagicMock(spec=User)
    user.id = ADMIN_ID
    update.effective_user = user
    update.message = message
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID):
        await help_command(update, context)

    message.reply_text.assert_called_once()
    reply_msg = message.reply_text.call_args[0][0]
    for cmd in ("/search", "/buy", "/sell", "/positions", "/orders", "/admin", "/cancel", "/help"):
        assert cmd in reply_msg, f"{cmd} missing from /help output"
    # Rarely-used ops commands must NOT be listed flat anymore — they're
    # reachable via /admin's submenu instead.
    for cmd in ("/status", "/health", "/restart", "/tail", "/backup_env"):
        assert cmd not in reply_msg, f"{cmd} should be behind /admin, not listed flat"


@pytest.mark.anyio
async def test_start_and_help_return_identical_message():
    update = MagicMock(spec=Update)
    message = AsyncMock(spec=Message)
    user = MagicMock(spec=User)
    user.id = ADMIN_ID
    update.effective_user = user
    update.message = message
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID):
        await start_command(update, context)
        start_msg = message.reply_text.call_args[0][0]
        message.reply_text.reset_mock()
        await help_command(update, context)
        help_msg = message.reply_text.call_args[0][0]

    assert start_msg == help_msg

@pytest.mark.anyio
async def test_status_command_success():
    # Mock update and context
    update = MagicMock(spec=Update)
    message = AsyncMock(spec=Message)

    # Mock effective_user to pass @admin_only decorator checks
    user = MagicMock(spec=User)
    user.id = 1344481918
    user.username = "admin_user"
    update.effective_user = user
    update.message = message

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    mock_status = {
        "active": "active (running)",
        "pid": "12345",
        "uptime": "10h ago",
        "memory": "50M",
        "last_log": "Started Zerodha MCP"
    }

    # Patch service_manager.get_service_status and config.ADMIN_ID
    with patch("src.telegram_admin.handlers.service_manager.get_service_status", return_value=mock_status) as mock_get_status, \
         patch("src.telegram_admin.auth.ADMIN_ID", 1344481918):

        await status_command(update, context)

        mock_get_status.assert_called_once()
        message.reply_text.assert_called_once()
        reply_msg = message.reply_text.call_args[0][0]
        assert "Service Status: zerodha-mcp" in reply_msg
        assert "**Active**: active (running)" in reply_msg
        assert "**PID**: `12345`" in reply_msg
        assert "**Uptime**: 10h ago" in reply_msg
        assert "**Memory**: `50M`" in reply_msg
        assert "**Latest Log**: `Started Zerodha MCP`" in reply_msg


# ---------------------------------------------------------------------------
# Phase 23 — trading command handlers
# ---------------------------------------------------------------------------

def _admin_update_with_message():
    update = MagicMock(spec=Update)
    message = AsyncMock(spec=Message)
    user = MagicMock(spec=User)
    user.id = ADMIN_ID
    user.username = "admin_user"
    update.effective_user = user
    update.message = message
    return update, message


@pytest.mark.anyio
async def test_buy_command_resolves_and_prompts_confirmation():
    update, message = _admin_update_with_message()
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = ["RELIANCE", "1", "LIMIT", "2870"]
    context.user_data = {}

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID), \
         patch("src.execution.service.resolve_symbol", AsyncMock(return_value="2885")):
        await buy_command(update, context)

    # pending order stashed with the resolved security_id, awaiting confirmation
    pending = context.user_data.get("pending_order")
    assert pending is not None
    assert pending.security_id == "2885"
    assert pending.transaction_type == "BUY"
    assert pending.limit_price == 2870.0
    # a confirm keyboard was sent — no order placed yet
    assert message.reply_text.called
    assert message.reply_text.call_args.kwargs.get("reply_markup") is not None


@pytest.mark.anyio
async def test_buy_command_unknown_symbol_no_pending():
    update, message = _admin_update_with_message()
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = ["MADEUPSYM", "1"]
    context.user_data = {}

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID), \
         patch("src.execution.service.resolve_symbol", AsyncMock(return_value=None)):
        await buy_command(update, context)

    assert "pending_order" not in context.user_data
    assert message.reply_text.called
    assert "not found" in message.reply_text.call_args[0][0]


@pytest.mark.anyio
async def test_order_confirm_yes_places_order():
    from src.brokers.models import OrderRequest
    query = AsyncMock()
    query.data = "order_confirm:yes"
    query.message = AsyncMock()
    update = MagicMock(spec=Update)
    user = MagicMock(spec=User)
    user.id = ADMIN_ID
    user.username = "admin_user"
    update.effective_user = user
    update.callback_query = query

    req = OrderRequest(security_id="2885", exchange="NSE", segment="EQUITY",
                       transaction_type="BUY", quantity=1, symbol="RELIANCE")
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = {"pending_order": req}

    placed = {"status": "ok", "order_id": "DRV-1", "order_status": "O-PENDING"}
    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID), \
         patch("src.execution.service.submit_order", AsyncMock(return_value=placed)) as sub:
        await order_confirm_callback(update, context)

    sub.assert_awaited_once()
    assert sub.call_args.kwargs["source"] == "telegram"
    assert "pending_order" not in context.user_data  # consumed
    # success message mentions the order id
    assert any("DRV-1" in str(c.args[0]) for c in query.message.reply_text.call_args_list)


@pytest.mark.anyio
async def test_order_confirm_no_cancels_without_placing():
    from src.brokers.models import OrderRequest
    query = AsyncMock()
    query.data = "order_confirm:no"
    query.message = AsyncMock()
    update = MagicMock(spec=Update)
    user = MagicMock(spec=User)
    user.id = ADMIN_ID
    update.effective_user = user
    update.callback_query = query

    req = OrderRequest(security_id="1", exchange="NSE", segment="EQUITY",
                       transaction_type="BUY", quantity=1, symbol="TCS")
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = {"pending_order": req}

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID), \
         patch("src.execution.service.submit_order", AsyncMock()) as sub:
        await order_confirm_callback(update, context)

    sub.assert_not_awaited()
    assert "pending_order" not in context.user_data
    query.message.edit_text.assert_awaited()  # "Order cancelled."


# ---------------------------------------------------------------------------
# /search — symbol lookup before /buy or /sell
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_search_command_too_short_shows_usage():
    update, message = _admin_update_with_message()
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = ["r"]

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID), \
         patch("src.execution.service.search_symbols", AsyncMock()) as search:
        await search_command(update, context)

    search.assert_not_awaited()
    assert "Usage" in message.reply_text.call_args[0][0]


@pytest.mark.anyio
async def test_search_command_lists_matches():
    update, message = _admin_update_with_message()
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = ["reliance"]

    results = [{"symbol": "RELIANCE", "name": "Reliance Industries", "exchange": "NSE", "segment": "EQUITY"}]
    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID), \
         patch("src.execution.service.search_symbols", AsyncMock(return_value=results)):
        await search_command(update, context)

    reply = message.reply_text.call_args[0][0]
    assert "RELIANCE" in reply
    assert "Reliance Industries" in reply


@pytest.mark.anyio
async def test_search_command_shows_expiry_and_warns_on_ambiguous_symbol():
    # Regression: index options (NIFTY/SENSEX weekly series) can return
    # several rows sharing one display symbol, one per weekly expiry — /buy
    # and /sell can only resolve by that symbol text, so ordering is
    # ambiguous. /search must show the expiry per row and flag the ambiguity
    # rather than silently look like one normal result.
    update, message = _admin_update_with_message()
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = ["27500"]

    results = [
        {"symbol": "NIFTY-JUL2026-27500-PE", "name": "NIFTY", "exchange": "NSE",
         "segment": "DERIVATIVE", "expiry": "2026-07-02"},
        {"symbol": "NIFTY-JUL2026-27500-PE", "name": "NIFTY", "exchange": "NSE",
         "segment": "DERIVATIVE", "expiry": "2026-07-09"},
    ]
    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID), \
         patch("src.execution.service.search_symbols", AsyncMock(return_value=results)):
        await search_command(update, context)

    reply = message.reply_text.call_args[0][0]
    assert "2026-07-02" in reply
    assert "2026-07-09" in reply
    assert "multiple expiries" in reply.lower()
    assert "NIFTY-JUL2026-27500-PE" in reply


@pytest.mark.anyio
async def test_search_command_no_ambiguity_warning_for_unique_symbols():
    update, message = _admin_update_with_message()
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = ["reliance"]

    results = [{"symbol": "RELIANCE", "name": "Reliance Industries", "exchange": "NSE", "segment": "EQUITY"}]
    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID), \
         patch("src.execution.service.search_symbols", AsyncMock(return_value=results)):
        await search_command(update, context)

    reply = message.reply_text.call_args[0][0]
    assert "multiple expiries" not in reply.lower()


@pytest.mark.anyio
async def test_search_command_no_matches():
    update, message = _admin_update_with_message()
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = ["notasymbol"]

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID), \
         patch("src.execution.service.search_symbols", AsyncMock(return_value=[])):
        await search_command(update, context)

    assert "No symbols found" in message.reply_text.call_args[0][0]


@pytest.mark.anyio
async def test_search_command_bare_tap_forces_reply_keyboard():
    """Tapping /search from the "/" picker sends it with zero args — the
    usage reply must use ForceReply so it's obvious typing (not another
    tap) is what's needed next (2026-07-11: this is what "I click search
    and can't type after the symbol" was actually describing)."""
    update, message = _admin_update_with_message()
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = []

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID):
        await search_command(update, context)

    call = message.reply_text.call_args
    assert "Usage" in call.args[0]
    assert "reply_markup" in call.kwargs
    assert call.kwargs["reply_markup"].force_reply is True


@pytest.mark.anyio
async def test_buy_command_bare_tap_forces_reply_keyboard():
    update, message = _admin_update_with_message()
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = []

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID):
        await buy_command(update, context)

    call = message.reply_text.call_args
    assert "Usage" in call.args[0]
    assert "reply_markup" in call.kwargs
    assert call.kwargs["reply_markup"].force_reply is True


@pytest.mark.anyio
async def test_buy_command_bad_args_does_not_force_reply():
    """A typo/mistake (some args present, just wrong) is a different signal
    than a bare tap — don't force the reply keyboard, the usage hint alone
    is enough since the user was already typing."""
    update, message = _admin_update_with_message()
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = ["RELIANCE", "notanumber"]

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID):
        await buy_command(update, context)

    call = message.reply_text.call_args
    assert "reply_markup" not in call.kwargs or call.kwargs.get("reply_markup") is None


# ---------------------------------------------------------------------------
# /admin menu — categorized navigation over rarely-used admin/ops commands
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_admin_command_shows_category_menu():
    update, message = _admin_update_with_message()
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID):
        await admin_command(update, context)

    message.reply_text.assert_awaited_once()
    kwargs = message.reply_text.call_args.kwargs
    assert "reply_markup" in kwargs
    # 4 categories = 4 rows on the top-level menu
    assert len(kwargs["reply_markup"].inline_keyboard) == 4


@pytest.mark.anyio
async def test_admin_menu_callback_shows_category_submenu():
    query = AsyncMock()
    query.data = "admin_menu:service"
    query.message = AsyncMock()
    update = MagicMock(spec=Update)
    user = MagicMock(spec=User)
    user.id = ADMIN_ID
    update.effective_user = user
    update.callback_query = query
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID):
        await admin_menu_callback(update, context)

    query.answer.assert_awaited_once()
    query.message.edit_text.assert_awaited_once()
    text = query.message.edit_text.call_args.args[0]
    assert "Service" in text


@pytest.mark.anyio
async def test_admin_menu_callback_root_returns_to_top_menu():
    query = AsyncMock()
    query.data = "admin_menu:_root"
    query.message = AsyncMock()
    update = MagicMock(spec=Update)
    user = MagicMock(spec=User)
    user.id = ADMIN_ID
    update.effective_user = user
    update.callback_query = query
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID):
        await admin_menu_callback(update, context)

    kwargs = query.message.edit_text.call_args.kwargs
    assert len(kwargs["reply_markup"].inline_keyboard) == 4


@pytest.mark.anyio
async def test_admin_menu_callback_unknown_category():
    query = AsyncMock()
    query.data = "admin_menu:not_a_real_category"
    query.message = AsyncMock()
    update = MagicMock(spec=Update)
    user = MagicMock(spec=User)
    user.id = ADMIN_ID
    update.effective_user = user
    update.callback_query = query
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID):
        await admin_menu_callback(update, context)

    assert "Unknown category" in query.message.edit_text.call_args.args[0]


@pytest.mark.anyio
async def test_admin_cmd_callback_replies_with_command_to_type():
    """Never runs anything directly — pure navigation, per design (2026-07-11):
    zero risk to any existing handler's behavior."""
    query = AsyncMock()
    query.data = "admin_cmd:/restart"
    query.message = AsyncMock()
    update = MagicMock(spec=Update)
    user = MagicMock(spec=User)
    user.id = ADMIN_ID
    update.effective_user = user
    update.callback_query = query
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID):
        await admin_cmd_callback(update, context)

    query.message.reply_text.assert_awaited_once()
    call = query.message.reply_text.call_args
    assert call.args[0] == "Type: /restart"
    # ForceReply pops the client's keyboard open — the fix for "tapping a
    # menu item sends it immediately, I can't type args after" (2026-07-11).
    assert "reply_markup" in call.kwargs


@pytest.mark.anyio
async def test_admin_commands_rejected_for_non_admin():
    query = AsyncMock()
    query.data = "admin_menu:service"
    query.message = AsyncMock()
    update = MagicMock(spec=Update)
    user = MagicMock(spec=User)
    user.id = 999999  # not ADMIN_ID
    update.effective_user = user
    update.callback_query = query
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID):
        await admin_menu_callback(update, context)

    query.answer.assert_not_awaited()
    query.message.edit_text.assert_not_awaited()
