"""
HRReach Bot - Database Module
JSON-based persistent storage for bot data, mail logs, and statistics.
"""

import json
import os
from datetime import datetime

# Path to the JSON database file
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database.json")

# Default database structure
DEFAULT_DB = {
    "total_sent": 0,
    "success": 0,
    "failed": 0,
    "subject": "Application for DevOps Engineer Fresher",
    "message": (
        "Hello Sir/Madam,\n\n"
        "I hope this email finds you well. I am writing to express my interest "
        "in any available fresher positions at your esteemed organization.\n\n"
        "Please find my resume attached for your review. I would be grateful "
        "for the opportunity to discuss how my skills and enthusiasm can "
        "contribute to your team.\n\n"
        "Thank you for your time and consideration.\n\n"
        "Best regards,\n"
        "Sundhar K"
    ),
    "mails": []
}


def _ensure_db_exists():
    """Create the database file with default values if it doesn't exist."""
    if not os.path.exists(DB_PATH):
        with open(DB_PATH, "w") as f:
            json.dump(DEFAULT_DB, f, indent=2)


def load_db() -> dict:
    """Load and return the entire database."""
    _ensure_db_exists()
    try:
        with open(DB_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        # If corrupted, reset to default
        save_db(DEFAULT_DB)
        return DEFAULT_DB.copy()


def save_db(data: dict):
    """Save the entire database to disk and sync to GitHub."""
    with open(DB_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    # Auto-sync to GitHub for persistence across redeploys
    try:
        from utils.github_sync import sync_database
        sync_database()
    except Exception:
        pass  # Don't break saves if sync fails


def get_subject() -> str:
    """Get the current email subject."""
    db = load_db()
    return db.get("subject", DEFAULT_DB["subject"])


def set_subject(subject: str):
    """Update the email subject."""
    db = load_db()
    db["subject"] = subject
    save_db(db)


def get_message() -> str:
    """Get the current email body message."""
    db = load_db()
    return db.get("message", DEFAULT_DB["message"])


def set_message(message: str):
    """Update the email body message."""
    db = load_db()
    db["message"] = message
    save_db(db)


def get_stats() -> dict:
    """Get mail statistics."""
    db = load_db()
    return {
        "total_sent": db.get("total_sent", 0),
        "success": db.get("success", 0),
        "failed": db.get("failed", 0)
    }


def log_mail(email: str, subject: str, status: str):
    """
    Log a sent mail entry and update statistics.

    Args:
        email: The recipient HR email address
        subject: The email subject used
        status: 'success' or 'failed'
    """
    db = load_db()

    # Update counters
    db["total_sent"] = db.get("total_sent", 0) + 1
    if status == "success":
        db["success"] = db.get("success", 0) + 1
    else:
        db["failed"] = db.get("failed", 0) + 1

    # Add mail log entry
    log_entry = {
        "email": email,
        "subject": subject,
        "status": status,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    db.setdefault("mails", []).append(log_entry)

    save_db(db)


def get_recent_logs(count: int = 5) -> list:
    """Get the most recent mail log entries."""
    db = load_db()
    mails = db.get("mails", [])
    return mails[-count:] if mails else []
