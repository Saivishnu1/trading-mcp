import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, Message, User
from telegram.ext import ContextTypes
from src.telegram_admin.handlers import (
    status_command,
    buy_command,
    order_confirm_callback,
    search_command,
    help_command,
    start_command,
)

ADMIN_ID = 1344481918


@pytest.mark.anyio
async def test_help_command_lists_all_commands():
    """/help exists so the command list is available on demand, not just at
    /start — must cover every command actually registered in main.py, not
    drift out of sync as new ones get added."""
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
    for cmd in (
        "/search", "/buy", "/sell", "/positions", "/orders",
        "/env", "/show", "/status", "/health", "/restart", "/reload",
        "/tail", "/logs", "/backup", "/backup_env", "/disk", "/uptime",
        "/ip", "/cancel", "/help",
    ):
        assert cmd in reply_msg, f"{cmd} missing from /help output"


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
async def test_search_command_no_matches():
    update, message = _admin_update_with_message()
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = ["notasymbol"]

    with patch("src.telegram_admin.auth.ADMIN_ID", ADMIN_ID), \
         patch("src.execution.service.search_symbols", AsyncMock(return_value=[])):
        await search_command(update, context)

    assert "No symbols found" in message.reply_text.call_args[0][0]
