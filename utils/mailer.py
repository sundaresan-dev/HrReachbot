"""
HRReach Bot - Mailer Module
Sends emails via Resend API (HTTPS — works on Railway/Render).
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
#   RESEND API (Primary — works on Railway/Render via HTTPS)
# ═══════════════════════════════════════════════════════════════════════════

def _send_via_resend(to_email: str, subject: str, message: str) -> dict:
    """Send email via Resend REST API. Works everywhere (HTTPS, port 443)."""
    resend_key = os.getenv("RESEND_API_KEY")
    sender_email = os.getenv("EMAIL", "")
    sender_name = os.getenv("SENDER_NAME", "Sundhar K")

    if not resend_key:
        return {"success": False, "error": "RESEND_API_KEY not configured"}

    try:
        # Read and encode the resume
        with open(RESUME_PATH, "rb") as f:
            resume_b64 = base64.b64encode(f.read()).decode()

        # Build the payload
        payload = {
            "from": f"{sender_name} <onboarding@resend.dev>",
            "to": [to_email.strip()],
            "reply_to": sender_email,
            "subject": subject,
            "text": message,
            "attachments": [
                {
                    "content": resume_b64,
                    "filename": "resume.pdf",
                }
            ],
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {resend_key}",
                "Content-Type": "application/json",
            },
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())

        if result.get("id"):
            logger.info(f"✅ Resend: Email sent to {to_email} (ID: {result['id']})")
            return {"success": True, "error": None}
        return {"success": False, "error": f"Resend: Unexpected response: {result}"}

    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else str(e)
        logger.error(f"Resend API error: {e.code} - {body}")
        return {"success": False, "error": f"Resend error ({e.code}): {body}"}
    except Exception as e:
        logger.error(f"Resend failed: {e}")
        return {"success": False, "error": f"Resend error: {str(e)}"}


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

    # --- Method 1: Resend API (works on Railway/Render) ---
    resend_key = os.getenv("RESEND_API_KEY")
    if resend_key:
        logger.info(f"Sending via Resend API to {to_email}...")
        result = _send_via_resend(to_email, subject, message)
        if result["success"]:
            return result
        errors.append(f"Resend: {result['error']}")
        logger.warning(f"Resend failed: {result['error']}")

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
