"""Read LinkedIn verification PIN from Gmail inbox via IMAP."""
from __future__ import annotations

import email
import imaplib
import logging
import re
import time
from email.header import decode_header

logger = logging.getLogger(__name__)

# LinkedIn sends PINs from these senders
LINKEDIN_SENDERS = ("security-noreply@linkedin.com", "linkedin.com")


def read_linkedin_pin(
    email_address: str,
    app_password: str,
    max_wait_seconds: int = 90,
    poll_interval: int = 10,
) -> str | None:
    """Poll Gmail IMAP for the latest LinkedIn verification PIN.

    Args:
        email_address: Gmail address (e.g., user@gmail.com)
        app_password: Gmail app-specific password for IMAP
        max_wait_seconds: How long to wait for the PIN email to arrive
        poll_interval: Seconds between inbox checks

    Returns:
        6-digit PIN string, or None if not found within timeout.
    """
    deadline = time.time() + max_wait_seconds
    logger.info("Waiting for LinkedIn PIN email (up to %ds)...", max_wait_seconds)

    while time.time() < deadline:
        pin = _check_inbox_for_pin(email_address, app_password)
        if pin:
            logger.info("Found LinkedIn PIN: %s", pin)
            return pin
        logger.debug("No PIN email yet — retrying in %ds", poll_interval)
        time.sleep(poll_interval)

    logger.warning("Timed out waiting for LinkedIn PIN email")
    return None


def _check_inbox_for_pin(email_address: str, app_password: str) -> str | None:
    """Check Gmail inbox for recent LinkedIn verification email and extract PIN."""
    mail = None
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(email_address, app_password)
        mail.select("INBOX")

        # Search for recent LinkedIn emails (last 5 minutes)
        # Search by FROM and recent date
        status, data = mail.search(None, '(FROM "security-noreply@linkedin.com" UNSEEN)')
        if status != "OK" or not data[0]:
            # Also try seen messages — LinkedIn PIN emails may be read by other clients
            status, data = mail.search(None, '(FROM "security-noreply@linkedin.com")')
            if status != "OK" or not data[0]:
                return None

        # Get the most recent email
        email_ids = data[0].split()
        if not email_ids:
            return None

        # Check the last 3 emails (most recent first)
        for eid in reversed(email_ids[-3:]):
            status, msg_data = mail.fetch(eid, "(RFC822)")
            if status != "OK":
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            # Check if it's recent (within last 5 minutes)
            date_str = msg.get("Date", "")

            # Extract PIN from subject or body
            subject = _decode_header(msg.get("Subject", ""))
            pin = _extract_pin(subject)
            if pin:
                return pin

            # Check body
            body = _get_email_body(msg)
            pin = _extract_pin(body)
            if pin:
                return pin

        return None

    except imaplib.IMAP4.error as e:
        logger.error("IMAP error: %s", e)
        return None
    except Exception as e:
        logger.error("Error reading email for PIN: %s", e)
        return None
    finally:
        if mail:
            try:
                mail.close()
                mail.logout()
            except Exception:
                pass


def _decode_header(header_val: str) -> str:
    """Decode email header value."""
    parts = decode_header(header_val)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _get_email_body(msg: email.message.Message) -> str:
    """Extract plain text body from email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
            elif content_type == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""


def _extract_pin(text: str) -> str | None:
    """Extract a 6-digit PIN from text.

    LinkedIn PINs are 6-digit numbers, typically presented as:
    - "Your verification code is 123456"
    - "123456" in the subject line
    - "Enter this code: 123456"
    """
    if not text:
        return None

    # Look for common LinkedIn PIN patterns
    patterns = [
        r"(?:verification\s+code|pin|code)\s*(?:is|:)?\s*(\d{6})",
        r"(\d{6})",  # Fallback: any 6-digit number
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)

    return None
