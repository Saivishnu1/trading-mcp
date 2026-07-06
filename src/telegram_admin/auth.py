import logging
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from src.telegram_admin.config import ADMIN_ID

logger = logging.getLogger(__name__)

def admin_only(func):
    """Decorator to restrict handler access to the ADMIN_ID only.
    
    Any request from a user other than ADMIN_ID is silently ignored 
    and logged for security auditing.
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_user:
            logger.warning("Received update with no effective user.")
            return
        
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            logger.warning(
                "SECURITY: Unauthorized access attempt by user %d (@%s)",
                user_id,
                update.effective_user.username or "unknown"
            )
            return
            
        return await func(update, context, *args, **kwargs)
    return wrapper
