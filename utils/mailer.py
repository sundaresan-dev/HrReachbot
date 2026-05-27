"""
HRReach Bot - Mailer Module
Sends emails via Gmail SMTP with resume attachment.
Uses SSL (port 465) as primary, STARTTLS (port 587) as fallback.
"""

import os
import re
import ssl
import socket
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

logger = logging.getLogger(__name__)

# SMTP Configuration
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT_SSL = 465
SMTP_PORT_TLS = 587

# Path to the resume file
RESUME_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resume.pdf")


def validate_email(email: str) -> bool:
    """
    Validate an email address format.

    Args:
        email: The email address to validate

    Returns:
        True if the email format is valid, False otherwise
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email.strip()))


def is_resume_available() -> bool:
    """Check if a resume file exists and is not empty."""
    return os.path.exists(RESUME_PATH) and os.path.getsize(RESUME_PATH) > 0


# ═══════════════════════════════════════════════════════════════════════════
#   Gmail SMTP Methods
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_ipv4(host: str, port: int):
    """Force IPv4 DNS resolution to avoid IPv6 network unreachable errors."""
    try:
        results = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        if results:
            return results[0][4][0]  # Return the IPv4 address
    except socket.gaierror:
        pass
    return host


def _send_via_ssl(sender_email: str, app_password: str, to_email: str, msg: str) -> dict:
    """Try sending via SMTP_SSL on port 465 (direct SSL connection)."""
    try:
        ipv4_addr = _resolve_ipv4(SMTP_SERVER, SMTP_PORT_SSL)
        logger.info(f"Trying SSL (port {SMTP_PORT_SSL}) via {ipv4_addr}...")

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(ipv4_addr, SMTP_PORT_SSL, timeout=30, context=context) as server:
            server.login(sender_email, app_password)
            server.sendmail(sender_email, to_email.strip(), msg)

        return {"success": True, "error": None}
    except Exception as e:
        logger.warning(f"SSL method failed: {e}")
        return {"success": False, "error": str(e)}


def _send_via_starttls(sender_email: str, app_password: str, to_email: str, msg: str) -> dict:
    """Try sending via STARTTLS on port 587."""
    try:
        ipv4_addr = _resolve_ipv4(SMTP_SERVER, SMTP_PORT_TLS)
        logger.info(f"Trying STARTTLS (port {SMTP_PORT_TLS}) via {ipv4_addr}...")

        with smtplib.SMTP(ipv4_addr, SMTP_PORT_TLS, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender_email, app_password)
            server.sendmail(sender_email, to_email.strip(), msg)

        return {"success": True, "error": None}
    except Exception as e:
        logger.warning(f"STARTTLS method failed: {e}")
        return {"success": False, "error": str(e)}


def send_email(to_email: str, subject: str, message: str) -> dict:
    """
    Send an email with the resume attached via Gmail SMTP.
    Tries SSL (port 465) first, then falls back to STARTTLS (port 587).
    Forces IPv4 to avoid network unreachable errors on cloud platforms.

    Args:
        to_email: Recipient HR email address
        subject: Email subject line
        message: Email body text

    Returns:
        dict with 'success' (bool) and 'error' (str or None)
    """
    # Load credentials from environment
    sender_email = os.getenv("EMAIL")
    app_password = os.getenv("APP_PASSWORD")

    # --- Validation Checks ---
    if not sender_email or not app_password:
        return {
            "success": False,
            "error": "Email credentials not configured. Check EMAIL and APP_PASSWORD in .env"
        }

    if not validate_email(to_email):
        return {
            "success": False,
            "error": f"Invalid email address: {to_email}"
        }

    if not is_resume_available():
        return {
            "success": False,
            "error": "Resume file not found. Please upload a resume first."
        }

    if not subject or not subject.strip():
        return {
            "success": False,
            "error": "Email subject is empty. Please update the subject first."
        }

    if not message or not message.strip():
        return {
            "success": False,
            "error": "Email message is empty. Please update the message first."
        }

    # --- Compose Email ---
    try:
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = to_email.strip()
        msg["Subject"] = subject

        # Attach the email body
        msg.attach(MIMEText(message, "plain"))

        # Attach the resume PDF
        with open(RESUME_PATH, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename=resume.pdf"
            )
            msg.attach(part)

        msg_string = msg.as_string()

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to compose email: {str(e)}"
        }

    errors = []

    # --- Method 1: SMTP SSL (port 465) ---
    result = _send_via_ssl(sender_email, app_password, to_email, msg_string)
    if result["success"]:
        logger.info(f"✅ Email sent via SSL to {to_email}")
        return result
    errors.append(f"SSL: {result['error']}")

    # --- Method 2: SMTP STARTTLS (port 587) ---
    result = _send_via_starttls(sender_email, app_password, to_email, msg_string)
    if result["success"]:
        logger.info(f"✅ Email sent via STARTTLS to {to_email}")
        return result
    errors.append(f"TLS: {result['error']}")

    # Both methods failed
    error_detail = " | ".join(errors)
    logger.error(f"All SMTP methods failed for {to_email}: {error_detail}")
    return {
        "success": False,
        "error": error_detail
    }
