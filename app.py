"""
HRReach Bot - Flask Application for Render/Railway Deployment
Provides a lightweight Flask web server alongside the Telegram bot.
Includes a keep-alive pinger to prevent Render free tier from sleeping.
"""

import os
import time
import logging
import threading
import urllib.request
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
    """Health check endpoint."""
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


# ─── Keep-Alive Pinger ─────────────────────────────────────────────────────

def keep_alive():
    """
    Ping the app's own health endpoint every 14 minutes to prevent
    Render free tier from spinning down after 15 mins of inactivity.
    """
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    port = os.getenv("PORT", "5000")

    if render_url:
        ping_url = f"{render_url}/health"
    else:
        ping_url = f"http://localhost:{port}/health"

    logger.info(f"🔄 Keep-alive pinger started (every 14 min) → {ping_url}")

    while True:
        time.sleep(840)  # 14 minutes
        try:
            urllib.request.urlopen(ping_url, timeout=10)
            logger.info("💓 Keep-alive ping sent successfully")
        except Exception as e:
            logger.warning(f"Keep-alive ping failed: {e}")


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
    # Start Flask in a background thread
    flask_thread = threading.Thread(target=start_flask_server, daemon=True)
    flask_thread.start()

    # Start keep-alive pinger in a background thread
    ping_thread = threading.Thread(target=keep_alive, daemon=True)
    ping_thread.start()

    # Run the bot in the MAIN thread (run_polling needs signal handlers)
    try:
        run_bot_polling()
    except Exception as e:
        logger.error(f"Bot failed: {e}")
        raise
