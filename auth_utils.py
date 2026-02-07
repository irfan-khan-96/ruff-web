"""
Authentication helpers: token generation and email sending.
"""

from typing import Optional, Tuple
import logging
import smtplib
from email.message import EmailMessage

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask import current_app

from models import db, User

logger = logging.getLogger(__name__)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"],
        salt=current_app.config["SECURITY_PASSWORD_SALT"],
    )


def generate_token(user: User, purpose: str) -> str:
    payload = {
        "user_id": user.id,
        "purpose": purpose,
        "pw": user.password_hash,
    }
    return _serializer().dumps(payload)


def verify_token(token: str, purpose: str, max_age: int) -> Tuple[Optional[User], Optional[str]]:
    try:
        data = _serializer().loads(token, max_age=max_age)
    except SignatureExpired:
        return None, "expired"
    except BadSignature:
        return None, "invalid"

    if data.get("purpose") != purpose:
        return None, "invalid"

    user = db.session.get(User, data.get("user_id"))
    if user is None:
        return None, "invalid"

    if data.get("pw") != user.password_hash:
        return None, "invalid"

    return user, None


def send_email(recipient: str, subject: str, body: str) -> None:
    """
    Send email via SMTP if configured; otherwise log and return.
    """
    host = current_app.config.get("SMTP_HOST")
    from_addr = current_app.config.get("SMTP_FROM")

    if not host or not from_addr:
        logger.warning("SMTP not configured. Email to %s | %s | %s", recipient, subject, body)
        return

    port = current_app.config.get("SMTP_PORT", 587)
    username = current_app.config.get("SMTP_USER")
    password = current_app.config.get("SMTP_PASSWORD")
    use_tls = current_app.config.get("SMTP_USE_TLS", True)
    use_ssl = current_app.config.get("SMTP_USE_SSL", False)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_addr
    message["To"] = recipient
    message.set_content(body)

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
        with server:
            if use_tls and not use_ssl:
                server.starttls()
            if username and password:
                server.login(username, password)
            server.send_message(message)
        logger.info("Email sent to %s | %s", recipient, subject)
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", recipient, exc)
