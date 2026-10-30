"""
Authentication helpers: passwordless sign-in links, sessions, and email.
"""

from typing import Optional, Tuple
import hashlib
import hmac
import logging
import secrets
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


def session_fingerprint(user: User) -> str:
    """
    Keyed digest of the user's session epoch. "Sign out everywhere" bumps the
    epoch, which invalidates every existing session cookie at once.
    """
    return hmac.new(
        current_app.config["SECRET_KEY"].encode(),
        f"session:{user.id}:{user.session_epoch or 0}".encode(),
        hashlib.sha256,
    ).hexdigest()


def start_session(session, user: User) -> None:
    """Log a user in (fresh session: no fixation)."""
    session.clear()
    session["user_id"] = user.id
    session["epoch"] = session_fingerprint(user)
    session.permanent = True


def load_session_user(session) -> Optional[User]:
    """
    Return the logged-in user for a Flask session, or None.

    Clears the session when it no longer identifies a valid user: the account
    was deleted, or the user signed out everywhere since this session began.
    """
    user_id = session.get("user_id")
    if user_id is None:
        return None

    user = db.session.get(User, user_id)
    if user is None or not hmac.compare_digest(str(session.get("epoch", "")), session_fingerprint(user)):
        session.clear()
        return None
    return user


# Email sign-in links -----------------------------------------------------------
# Two kinds: "login" for an existing account (carries the account's single-use
# login_nonce) and "signup" for an email with no account yet (single use
# because the account exists once it has been used).

def login_link_token(user: User) -> str:
    """A sign-in token for an existing account; replaces any earlier link."""
    user.login_nonce = secrets.token_urlsafe(24)
    return _serializer().dumps({"purpose": "login", "uid": user.id, "nonce": user.login_nonce})


def signup_link_token(email: str) -> str:
    """A token that creates the account for `email` when used."""
    return _serializer().dumps({"purpose": "signup", "email": email})


def read_link_token(token: str, max_age: int) -> Tuple[Optional[dict], Optional[str]]:
    """Signed, unexpired token payload, or (None, "expired" | "invalid")."""
    try:
        data = _serializer().loads(token, max_age=max_age)
    except SignatureExpired:
        return None, "expired"
    except BadSignature:
        return None, "invalid"
    if not isinstance(data, dict) or data.get("purpose") not in ("login", "signup"):
        return None, "invalid"
    return data, None


def send_email(recipient: str, subject: str, body: str) -> None:
    """
    Send email via SMTP if configured; otherwise log and return.
    """
    host = current_app.config.get("SMTP_HOST")
    from_addr = current_app.config.get("SMTP_FROM")

    if not host or not from_addr:
        if current_app.debug or current_app.config.get("MAIL_TO_LOG"):
            # Development / local stacks: the sign-in link appears in the log
            logger.warning("SMTP not configured. Email to %s | %s | %s", recipient, subject, body)
        else:
            # Never log the body in production: it contains live account tokens
            logger.error("SMTP not configured; email to %s not sent (%s)", recipient, subject)
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
