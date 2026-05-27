"""
HRReach Bot - Authentication Module
Handles admin-only access control for the bot.
"""

import os
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes

# Load admin ID from environment variable
ADMIN_ID = int(os.getenv("ADMIN_ID", "6993392639"))


def is_admin(user_id: int) -> bool:
    """Check if the given user ID matches the admin ID."""
    return user_id == ADMIN_ID


def admin_only(func):
    """
    Decorator to restrict bot handlers to admin-only access.
    Sends 'Access Denied ❌' to unauthorized users.
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id

        if not is_admin(user_id):
            await update.message.reply_text(
                "🚫 *Access Denied* ❌\n\n"
                "You are not authorized to use this bot.\n"
                "This bot is restricted to admin use only.",
                parse_mode="Markdown"
            )
            return

        return await func(update, context, *args, **kwargs)

    return wrapper
