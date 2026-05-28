"""
HRReach Bot - Mailer Module
Sends emails via Brevo API (HTTPS — works on Railway/Render).
Falls back to Gmail SMTP on platforms that allow it.
"""

import os
import re
import ssl
import json
import base64
import socket
import smtplib
import logging
import urllib.request
import urllib.error
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

logger = logging.getLogger(__name__)

# SMTP Configuration (fallback)
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
#   BREVO API (Primary — works on Railway/Render via HTTPS)
# ═══════════════════════════════════════════════════════════════════════════

def _send_via_brevo(to_email: str, subject: str, message: str) -> dict:
    """Send email via Brevo REST API. Works everywhere (HTTPS, port 443)."""
    import requests as req_lib

    brevo_key = os.getenv("BREVO_API_KEY")
    sender_email = os.getenv("EMAIL", "")
    sender_name = os.getenv("SENDER_NAME", "Sundhar K")

    if not brevo_key:
        return {"success": False, "error": "BREVO_API_KEY not configured"}

    try:
        # Read and encode the resume
        with open(RESUME_PATH, "rb") as f:
            resume_b64 = base64.b64encode(f.read()).decode()

        # Build the payload
        payload = {
            "sender": {"name": sender_name, "email": sender_email},
            "to": [{"email": to_email.strip()}],
            "subject": subject,
            "textContent": message,
            "attachment": [{"content": resume_b64, "name": "resume.pdf"}],
        }

        resp = req_lib.post(
            "https://api.brevo.com/v3/smtp/email",
            json=payload,
            headers={
                "api-key": brevo_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=30,
        )

        if resp.status_code in (200, 201):
            result = resp.json()
            logger.info(f"✅ Brevo: Email sent to {to_email} (ID: {result.get('messageId', 'unknown')})")
            return {"success": True, "error": None}
        else:
            logger.error(f"Brevo API error: {resp.status_code} - {resp.text}")
            return {"success": False, "error": f"Brevo error ({resp.status_code}): {resp.text}"}

    except Exception as e:
        logger.error(f"Brevo failed: {e}")
        return {"success": False, "error": f"Brevo error: {str(e)}"}


# ═══════════════════════════════════════════════════════════════════════════
#   SMTP Fallback (for platforms that allow SMTP)
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_ipv4(host: str, port: int):
    """Force IPv4 DNS resolution to avoid IPv6 network unreachable errors."""
    try:
        results = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        if results:
            return results[0][4][0]
    except socket.gaierror:
        pass
    return host


def _send_via_ssl(sender_email: str, app_password: str, to_email: str, msg: str) -> dict:
    """Try sending via SMTP_SSL on port 465 (direct SSL connection)."""
    try:
        ipv4_addr = _resolve_ipv4(SMTP_SERVER, SMTP_PORT_SSL)
        logger.info(f"Trying SSL (port {SMTP_PORT_SSL}) via {ipv4_addr}...")

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(ipv4_addr, SMTP_PORT_SSL, timeout=15, context=context) as server:
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

        with smtplib.SMTP(ipv4_addr, SMTP_PORT_TLS, timeout=15) as server:
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
    Send an email with the resume attached.
    Priority: Resend API → Gmail SMTP SSL → Gmail SMTP STARTTLS.

    Args:
        to_email: Recipient HR email address
        subject: Email subject line
        message: Email body text

    Returns:
        dict with 'success' (bool) and 'error' (str or None)
    """
    sender_email = os.getenv("EMAIL")
    app_password = os.getenv("APP_PASSWORD")

    # --- Validation Checks ---
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

    errors = []

    # --- Method 1: Brevo API (works on Railway/Render) ---
    brevo_key = os.getenv("BREVO_API_KEY")
    if brevo_key:
        logger.info(f"Sending via Brevo API to {to_email}...")
        result = _send_via_brevo(to_email, subject, message)
        if result["success"]:
            return result
        errors.append(f"Brevo: {result['error']}")
        logger.warning(f"Brevo failed: {result['error']}")

    # --- SMTP Fallback (needs EMAIL + APP_PASSWORD) ---
    if sender_email and app_password:
        # Compose MIME email for SMTP
        try:
            msg = MIMEMultipart()
            msg["From"] = sender_email
            msg["To"] = to_email.strip()
            msg["Subject"] = subject
            msg.attach(MIMEText(message, "plain"))

            with open(RESUME_PATH, "rb") as attachment:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(attachment.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    "attachment; filename=resume.pdf"
                )
                msg.attach(part)

            msg_string = msg.as_string()
        except Exception as e:
            errors.append(f"Compose: {str(e)}")
            error_detail = " | ".join(errors)
            return {"success": False, "error": error_detail}

        # Try SSL (port 465)
        result = _send_via_ssl(sender_email, app_password, to_email, msg_string)
        if result["success"]:
            logger.info(f"✅ Email sent via SSL to {to_email}")
            return result
        errors.append(f"SSL: {result['error']}")

        # Try STARTTLS (port 587)
        result = _send_via_starttls(sender_email, app_password, to_email, msg_string)
        if result["success"]:
            logger.info(f"✅ Email sent via STARTTLS to {to_email}")
            return result
        errors.append(f"TLS: {result['error']}")
    elif not resend_key:
        return {
            "success": False,
            "error": "No email method configured. Set RESEND_API_KEY or EMAIL+APP_PASSWORD in .env"
        }

    # All methods failed
    error_detail = " | ".join(errors)
    logger.error(f"All methods failed for {to_email}: {error_detail}")
    return {
        "success": False,
        "error": error_detail
    }
