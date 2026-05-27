"""
HRReach Bot - Flask Application for Railway Deployment
Provides a lightweight Flask web server alongside the Telegram bot.
Uses polling mode for the bot with a Flask health-check server.
"""

import os
import logging
import threading
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Flask App ──────────────────────────────────────────────────────────────
app = Flask(__name__)


@app.route("/")
def home():
    """Health check endpoint for Railway."""
    return jsonify({
        "status": "running",
        "bot": "HRReach Bot",
        "version": "1.0.0",
        "message": "HRReach Bot is alive and operational! 🤖"
    })


@app.route("/health")
def health():
    """Detailed health check endpoint."""
    from utils.database import load_db, get_stats
    from utils.mailer import is_resume_available

    stats = get_stats()
    return jsonify({
        "status": "healthy",
        "resume_uploaded": is_resume_available(),
        "total_mails_sent": stats["total_sent"],
        "success": stats["success"],
        "failed": stats["failed"],
    })


def start_flask_server():
    """Start the Flask web server in a background thread."""
    port = int(os.getenv("PORT", 5000))
    logger.info(f"🌐 Flask server starting on port {port}...")
    app.run(host="0.0.0.0", port=port, use_reloader=False)


def run_bot_polling():
    """Run the Telegram bot in the main thread (requires signal handlers)."""
    from bot import create_bot_application
    application = create_bot_application()
    logger.info("🤖 HRReach Bot starting in polling mode...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    # Start Flask in a background thread (doesn't need signal handlers)
    flask_thread = threading.Thread(target=start_flask_server, daemon=True)
    flask_thread.start()

    # Run the bot in the MAIN thread (run_polling needs signal handlers)
    try:
        run_bot_polling()
    except Exception as e:
        logger.error(f"Bot failed: {e}")
        raise
