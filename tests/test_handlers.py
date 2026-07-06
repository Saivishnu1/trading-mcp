import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, Message, User
from telegram.ext import ContextTypes
from src.telegram_admin.handlers import status_command

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
