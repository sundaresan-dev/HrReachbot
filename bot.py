"""
HRReach Bot - Main Bot Module
Telegram bot for automated HR recruitment email sending.
Admin-only access with dashboard UI, resume management, and mail tracking.
"""

import os
import logging
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

from utils.auth import admin_only, is_admin
from utils.database import (
    load_db,
    get_subject,
    set_subject,
    get_message,
    set_message,
    get_stats,
    log_mail,
    get_recent_logs,
)
from utils.mailer import send_email, validate_email, is_resume_available, RESUME_PATH

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Conversation States ────────────────────────────────────────────────────
(
    STATE_AWAITING_RESUME,
    STATE_AWAITING_MESSAGE,
    STATE_AWAITING_SUBJECT,
    STATE_AWAITING_EMAIL,
) = range(4)

# ─── Dashboard Menu ─────────────────────────────────────────────────────────
DASHBOARD_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📄 Update Resume"), KeyboardButton("📝 Update Message")],
        [KeyboardButton("📌 Update Subject"), KeyboardButton("📨 Send Mail")],
        [KeyboardButton("📊 Statistics"), KeyboardButton("📋 Recent Logs")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)


# ─── /start Command ─────────────────────────────────────────────────────────
@admin_only
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display the main dashboard with keyboard menu."""
    welcome_text = (
        "🤖 *HRReach Bot — Dashboard*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Welcome back, Admin! 👋\n\n"
        "Use the menu below to manage your\n"
        "recruitment email automation.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📄 *Update Resume* — Upload new PDF\n"
        "📝 *Update Message* — Change email body\n"
        "📌 *Update Subject* — Change email subject\n"
        "📨 *Send Mail* — Send to an HR email\n"
        "📊 *Statistics* — View mail stats\n"
        "📋 *Recent Logs* — Last 5 sent emails\n"
        "━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=DASHBOARD_KEYBOARD,
    )


# ─── Cancel Handler (shared by all conversations) ───────────────────────────
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel any ongoing conversation and return to dashboard."""
    await update.message.reply_text(
        "❌ Operation cancelled. Returning to dashboard.",
        reply_markup=DASHBOARD_KEYBOARD,
    )
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════════
#   📄 RESUME UPLOAD
# ═══════════════════════════════════════════════════════════════════════════

async def resume_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt the admin to upload a resume PDF."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 *Access Denied* ❌", parse_mode="Markdown")
        return ConversationHandler.END

    current_status = "✅ Resume exists" if is_resume_available() else "❌ No resume uploaded"

    await update.message.reply_text(
        f"📄 *Update Resume*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Current status: {current_status}\n\n"
        f"📎 Send me your resume as a *PDF file*.\n"
        f"It will replace the existing one.\n\n"
        f"Type /cancel to go back.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return STATE_AWAITING_RESUME


async def resume_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the uploaded resume document."""
    document = update.message.document

    # Validate file type
    if not document.file_name.lower().endswith(".pdf"):
        await update.message.reply_text(
            "⚠️ *Invalid file type!*\n\n"
            "Please upload a *PDF file* only.\n"
            "Try again or type /cancel.",
            parse_mode="Markdown",
        )
        return STATE_AWAITING_RESUME

    # Validate file size (max 20 MB)
    if document.file_size > 20 * 1024 * 1024:
        await update.message.reply_text(
            "⚠️ *File too large!*\n\n"
            "Maximum file size is 20 MB.\n"
            "Try again or type /cancel.",
            parse_mode="Markdown",
        )
        return STATE_AWAITING_RESUME

    try:
        # Download and save the resume
        file = await context.bot.get_file(document.file_id)
        await file.download_to_drive(RESUME_PATH)

        # Sync resume to GitHub for persistence across redeploys
        try:
            from utils.github_sync import sync_resume
            sync_resume()
        except Exception:
            pass

        file_size_kb = document.file_size / 1024
        await update.message.reply_text(
            f"✅ *Resume Updated Successfully!*\n\n"
            f"📁 File: `resume.pdf`\n"
            f"📏 Size: `{file_size_kb:.1f} KB`\n\n"
            f"Your resume is ready for mailing.",
            parse_mode="Markdown",
            reply_markup=DASHBOARD_KEYBOARD,
        )
        logger.info("Resume updated successfully.")
    except Exception as e:
        logger.error(f"Resume upload failed: {e}")
        await update.message.reply_text(
            f"❌ *Upload Failed*\n\n"
            f"Error: `{str(e)}`\n\n"
            f"Please try again.",
            parse_mode="Markdown",
            reply_markup=DASHBOARD_KEYBOARD,
        )

    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════════
#   📝 UPDATE MESSAGE
# ═══════════════════════════════════════════════════════════════════════════

async def message_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt the admin to enter a new email body message."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 *Access Denied* ❌", parse_mode="Markdown")
        return ConversationHandler.END

    current_msg = get_message()
    preview = current_msg[:200] + "..." if len(current_msg) > 200 else current_msg

    await update.message.reply_text(
        f"📝 *Update Email Message*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*Current message:*\n"
        f"```\n{preview}\n```\n\n"
        f"✏️ Send me the new email body message.\n\n"
        f"Type /cancel to go back.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return STATE_AWAITING_MESSAGE


async def message_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save the new email body message."""
    new_message = update.message.text.strip()

    if not new_message:
        await update.message.reply_text(
            "⚠️ Message cannot be empty. Try again or type /cancel.",
        )
        return STATE_AWAITING_MESSAGE

    set_message(new_message)

    await update.message.reply_text(
        f"✅ *Email Message Updated!*\n\n"
        f"```\n{new_message[:300]}\n```",
        parse_mode="Markdown",
        reply_markup=DASHBOARD_KEYBOARD,
    )
    logger.info("Email message updated.")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════════
#   📌 UPDATE SUBJECT
# ═══════════════════════════════════════════════════════════════════════════

async def subject_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt the admin to enter a new email subject."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 *Access Denied* ❌", parse_mode="Markdown")
        return ConversationHandler.END

    current_subject = get_subject()
    await update.message.reply_text(
        f"📌 *Update Email Subject*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*Current subject:*\n"
        f"`{current_subject}`\n\n"
        f"✏️ Send me the new email subject line.\n\n"
        f"Type /cancel to go back.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return STATE_AWAITING_SUBJECT


async def subject_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save the new email subject."""
    new_subject = update.message.text.strip()

    if not new_subject:
        await update.message.reply_text(
            "⚠️ Subject cannot be empty. Try again or type /cancel.",
        )
        return STATE_AWAITING_SUBJECT

    set_subject(new_subject)

    await update.message.reply_text(
        f"✅ *Email Subject Updated!*\n\n"
        f"New subject: `{new_subject}`",
        parse_mode="Markdown",
        reply_markup=DASHBOARD_KEYBOARD,
    )
    logger.info(f"Email subject updated to: {new_subject}")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════════
#   📨 SEND MAIL
# ═══════════════════════════════════════════════════════════════════════════

async def sendmail_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt the admin to enter the HR email address."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 *Access Denied* ❌", parse_mode="Markdown")
        return ConversationHandler.END

    # Pre-flight checks
    if not is_resume_available():
        await update.message.reply_text(
            "⚠️ *No Resume Found!*\n\n"
            "Please upload a resume first using\n"
            "📄 *Update Resume*",
            parse_mode="Markdown",
            reply_markup=DASHBOARD_KEYBOARD,
        )
        return ConversationHandler.END

    subject = get_subject()
    message = get_message()

    await update.message.reply_text(
        f"📨 *Send Mail*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 Subject: `{subject}`\n"
        f"📄 Resume: ✅ Attached\n"
        f"📝 Message: ✅ Ready\n\n"
        f"✉️ Enter the HR email address:\n\n"
        f"Type /cancel to go back.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return STATE_AWAITING_EMAIL


async def sendmail_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the email to the provided HR address."""
    hr_email = update.message.text.strip()

    # Validate email format
    if not validate_email(hr_email):
        await update.message.reply_text(
            f"⚠️ *Invalid Email Address!*\n\n"
            f"`{hr_email}` is not a valid email.\n"
            f"Please enter a valid email or type /cancel.",
            parse_mode="Markdown",
        )
        return STATE_AWAITING_EMAIL

    # Show sending status
    status_msg = await update.message.reply_text(
        f"⏳ *Sending email...*\n\n"
        f"📧 To: `{hr_email}`\n"
        f"Please wait...",
        parse_mode="Markdown",
    )

    # Get current subject and message
    subject = get_subject()
    message = get_message()

    # Send the email
    result = send_email(hr_email, subject, message)

    if result["success"]:
        log_mail(hr_email, subject, "success")
        stats = get_stats()

        await status_msg.edit_text(
            f"✅ *Mail Sent Successfully!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📧 To: `{hr_email}`\n"
            f"📌 Subject: `{subject}`\n"
            f"📄 Resume: Attached\n\n"
            f"📊 Total sent: {stats['total_sent']} | "
            f"✅ {stats['success']} | ❌ {stats['failed']}",
            parse_mode="Markdown",
        )
        logger.info(f"Mail sent successfully to {hr_email}")
    else:
        log_mail(hr_email, subject, "failed")

        await status_msg.edit_text(
            f"❌ *Mail Failed*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📧 To: `{hr_email}`\n"
            f"⚠️ Error: `{result['error']}`\n\n"
            f"Please check your settings and try again.",
            parse_mode="Markdown",
        )
        logger.error(f"Mail failed to {hr_email}: {result['error']}")

    # Return to dashboard
    await update.message.reply_text(
        "🔙 Returning to dashboard...",
        reply_markup=DASHBOARD_KEYBOARD,
    )
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════════
#   📊 STATISTICS
# ═══════════════════════════════════════════════════════════════════════════

@admin_only
async def statistics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display mail statistics."""
    stats = get_stats()
    total = stats["total_sent"]
    success = stats["success"]
    failed = stats["failed"]
    rate = (success / total * 100) if total > 0 else 0

    resume_status = "✅ Uploaded" if is_resume_available() else "❌ Not uploaded"

    await update.message.reply_text(
        f"📊 *Mail Statistics*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📬 Total Sent:     `{total}`\n"
        f"✅ Successful:     `{success}`\n"
        f"❌ Failed:          `{failed}`\n"
        f"📈 Success Rate:   `{rate:.1f}%`\n\n"
        f"📄 Resume: {resume_status}\n"
        f"📌 Subject: `{get_subject()}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown",
        reply_markup=DASHBOARD_KEYBOARD,
    )


# ═══════════════════════════════════════════════════════════════════════════
#   📋 RECENT LOGS
# ═══════════════════════════════════════════════════════════════════════════

@admin_only
async def recent_logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display the last 5 sent emails."""
    logs = get_recent_logs(5)

    if not logs:
        await update.message.reply_text(
            "📋 *Recent Logs*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No emails sent yet.\n"
            "Use 📨 *Send Mail* to get started!",
            parse_mode="Markdown",
            reply_markup=DASHBOARD_KEYBOARD,
        )
        return

    log_text = "📋 *Recent Logs (Last 5)*\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, entry in enumerate(reversed(logs), 1):
        status_icon = "✅" if entry.get("status") == "success" else "❌"
        log_text += (
            f"*{i}.* {status_icon}\n"
            f"   📧 `{entry.get('email', 'N/A')}`\n"
            f"   🕐 {entry.get('timestamp', 'N/A')}\n\n"
        )

    log_text += "━━━━━━━━━━━━━━━━━━━━━━━"

    await update.message.reply_text(
        log_text,
        parse_mode="Markdown",
        reply_markup=DASHBOARD_KEYBOARD,
    )


# ═══════════════════════════════════════════════════════════════════════════
#   UNKNOWN / FALLBACK
# ═══════════════════════════════════════════════════════════════════════════

async def unknown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle unrecognized messages.
    If the text is a valid email address, auto-send the resume mail directly.
    """
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 *Access Denied* ❌", parse_mode="Markdown")
        return

    text = update.message.text.strip()

    # ── Quick Send: Auto-detect email and send mail directly ─────────────
    if validate_email(text):
        hr_email = text

        # Pre-flight: check resume
        if not is_resume_available():
            await update.message.reply_text(
                "⚠️ *No Resume Found!*\n\n"
                "Please upload a resume first using\n"
                "📄 *Update Resume*",
                parse_mode="Markdown",
                reply_markup=DASHBOARD_KEYBOARD,
            )
            return

        subject = get_subject()
        message = get_message()

        # Show sending status
        status_msg = await update.message.reply_text(
            f"⚡ *Quick Send — Sending email...*\n\n"
            f"📧 To: `{hr_email}`\n"
            f"📌 Subject: `{subject}`\n"
            f"Please wait...",
            parse_mode="Markdown",
        )

        # Send the email
        result = send_email(hr_email, subject, message)

        if result["success"]:
            log_mail(hr_email, subject, "success")
            stats = get_stats()

            await status_msg.edit_text(
                f"✅ *Mail Sent Successfully!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📧 To: `{hr_email}`\n"
                f"📌 Subject: `{subject}`\n"
                f"📄 Resume: Attached\n\n"
                f"📊 Total sent: {stats['total_sent']} | "
                f"✅ {stats['success']} | ❌ {stats['failed']}",
                parse_mode="Markdown",
            )
            logger.info(f"Quick send: Mail sent successfully to {hr_email}")
        else:
            log_mail(hr_email, subject, "failed")

            await status_msg.edit_text(
                f"❌ *Mail Failed*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📧 To: `{hr_email}`\n"
                f"⚠️ Error: `{result['error']}`\n\n"
                f"Please check your settings and try again.",
                parse_mode="Markdown",
            )
            logger.error(f"Quick send: Mail failed to {hr_email}: {result['error']}")

        return

    # ── Fallback: Not an email, show help ────────────────────────────────
    await update.message.reply_text(
        "🤔 I didn't understand that.\n"
        "Use the menu buttons or type /start.\n\n"
        "💡 *Tip:* You can also just type an email\n"
        "address directly to quick-send your resume!",
        parse_mode="Markdown",
        reply_markup=DASHBOARD_KEYBOARD,
    )


# ═══════════════════════════════════════════════════════════════════════════
#   BOT SETUP & RUN
# ═══════════════════════════════════════════════════════════════════════════

def create_bot_application() -> Application:
    """Build and configure the Telegram bot application."""
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise ValueError("BOT_TOKEN environment variable is not set!")

    # Build the application
    application = Application.builder().token(bot_token).build()

    # ── Conversation: Resume Upload ──────────────────────────────────────
    resume_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"^📄 Update Resume$"), resume_start),
        ],
        states={
            STATE_AWAITING_RESUME: [
                MessageHandler(filters.Document.ALL, resume_receive),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex(r"^/cancel$"), cancel),
        ],
    )

    # ── Conversation: Update Message ─────────────────────────────────────
    message_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"^📝 Update Message$"), message_start),
        ],
        states={
            STATE_AWAITING_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, message_receive),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex(r"^/cancel$"), cancel),
        ],
    )

    # ── Conversation: Update Subject ─────────────────────────────────────
    subject_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"^📌 Update Subject$"), subject_start),
        ],
        states={
            STATE_AWAITING_SUBJECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, subject_receive),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex(r"^/cancel$"), cancel),
        ],
    )

    # ── Conversation: Send Mail ──────────────────────────────────────────
    sendmail_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"^📨 Send Mail$"), sendmail_start),
        ],
        states={
            STATE_AWAITING_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, sendmail_receive),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex(r"^/cancel$"), cancel),
        ],
    )

    # ── Register Handlers ────────────────────────────────────────────────
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(resume_conv)
    application.add_handler(message_conv)
    application.add_handler(subject_conv)
    application.add_handler(sendmail_conv)
    application.add_handler(
        MessageHandler(filters.Regex(r"^📊 Statistics$"), statistics_command)
    )
    application.add_handler(
        MessageHandler(filters.Regex(r"^📋 Recent Logs$"), recent_logs_command)
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_handler)
    )

    return application


def run_bot():
    """Start the bot in polling mode (for local development)."""
    from dotenv import load_dotenv
    load_dotenv()

    application = create_bot_application()
    logger.info("🤖 HRReach Bot started in polling mode...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run_bot()
