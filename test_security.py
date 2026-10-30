"""
Security regression tests: secrets, tokens, sessions, Socket.IO auth, limits.
"""

import base64
import io
import json
import zlib

import pytest
from flask.sessions import SecureCookieSessionInterface

from app import create_app
from auth_utils import login_link_token, read_link_token, signup_link_token
from conftest import sign_in
from config import ProductionConfig, TestingConfig, DEV_SECRET_KEY, DEV_PASSWORD_SALT
from models import db, User
from sockets import socketio



@pytest.fixture
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def user(app):
    user = User(username="alice", email="alice@example.com", email_verified=True)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def client(app, user):
    """A test client signed in as `user`."""
    return sign_in(app.test_client(), user)


def _token_payload(token: str) -> dict:
    """Decode an itsdangerous token payload without the key (as an attacker could)."""
    compressed = token.startswith(".")
    data = token.lstrip(".").split(".")[0]
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    return json.loads(zlib.decompress(raw) if compressed else raw)


# Secrets ---------------------------------------------------------------------

@pytest.mark.parametrize("key, salt", [
    (DEV_SECRET_KEY, DEV_PASSWORD_SALT),
    ("k" * 64, DEV_PASSWORD_SALT),
    ("", "s" * 64),
])
def test_production_refuses_default_or_missing_secrets(monkeypatch, key, salt):
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", key)
    monkeypatch.setattr(ProductionConfig, "SECURITY_PASSWORD_SALT", salt)
    with pytest.raises(RuntimeError):
        create_app("production")


def test_production_starts_with_real_secrets(monkeypatch):
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "k" * 64)
    monkeypatch.setattr(ProductionConfig, "SECURITY_PASSWORD_SALT", "s" * 64)
    assert create_app("production")


# Tokens ----------------------------------------------------------------------

def test_link_tokens_carry_no_secrets_about_the_account(app, user):
    """Signed, not encrypted: anyone can read them, so they hold only ids and a nonce."""
    with app.test_request_context():
        token = login_link_token(user)
    payload = _token_payload(token)
    assert set(payload) == {"purpose", "uid", "nonce"} and payload["uid"] == user.id
    assert payload["nonce"] == user.login_nonce


def test_link_tokens_are_signed_and_expire(app, user):
    with app.test_request_context():
        token = login_link_token(user)
        assert read_link_token(token, 900)[1] is None
        assert read_link_token(token[:-2] + "xx", 900) == (None, "invalid")
        assert read_link_token(signup_link_token("a@example.com") + "x", 900) == (None, "invalid")
        assert read_link_token(token, -1) == (None, "expired")


def test_a_new_link_replaces_the_previous_one(app, user):
    with app.test_request_context():
        first = login_link_token(user)
        second = login_link_token(user)
    db.session.commit()
    client = app.test_client()
    assert client.post(f"/auth/{first}").headers["Location"].endswith("/login")
    assert client.post(f"/auth/{second}").headers["Location"].endswith("/")


# Sessions --------------------------------------------------------------------

def test_sign_out_everywhere_ends_every_session(app, user):
    phone, laptop = sign_in(app.test_client(), user), sign_in(app.test_client(), user)
    assert phone.get("/export").status_code == 200 and laptop.get("/export").status_code == 200
    assert phone.post("/logout/everywhere").status_code == 302
    assert laptop.get("/export").status_code == 302  # sent to sign in
    assert phone.get("/export").status_code == 302


def test_forged_cookie_without_fingerprint_is_rejected(app, user):
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    client = app.test_client()
    client.set_cookie("session", serializer.dumps({"user_id": user.id}))
    assert client.get("/export").status_code == 302


def test_logout_requires_post(client):
    assert client.get("/logout").status_code == 405
    assert client.post("/logout").status_code == 302
    assert client.get("/export").status_code == 302


# Socket.IO -------------------------------------------------------------------

def test_socket_rejects_anonymous_connections(app):
    socket = socketio.test_client(app, flask_test_client=app.test_client())
    assert not socket.is_connected()


def test_socket_relays_signals_between_logged_in_users(app, client):
    sender = socketio.test_client(app, flask_test_client=client)
    receiver = socketio.test_client(app, flask_test_client=client)
    assert sender.is_connected() and receiver.is_connected()

    sender.emit("join_room", {"room": "ABC123"})
    receiver.emit("join_room", {"room": "ABC123"})
    sender.get_received()
    sender.emit("signal", {"room": "ABC123", "payload": {"type": "offer"}})
    received = receiver.get_received()
    assert [(m["name"], m["args"][0]) for m in received] == [("signal", {"type": "offer"})]


def test_socket_ignores_invalid_rooms(app, client):
    socket = socketio.test_client(app, flask_test_client=client)
    socket.emit("join_room", {"room": "X" * 100})
    socket.emit("join_room", "not-a-dict")
    socket.emit("signal", {"room": 123, "payload": {}})
    assert socket.is_connected()


# Request and content limits --------------------------------------------------

def test_oversized_request_is_rejected(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "MAX_CONTENT_LENGTH", 1000)
    response = client.post("/share/import", data="x" * 2000, content_type="application/json")
    assert response.status_code == 413
    response = client.post(
        "/import",
        data={"file": (io.BytesIO(b"x" * 2000), "export.json")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 413


@pytest.mark.parametrize("payload, error", [
    ({"body": "x" * 50001}, "Stash body is too long"),
    ({"body": "ok", "title": "t" * 201}, "Stash title is too long"),
    ({"body": "ok", "tags": ["x" * 51]}, "Invalid tags"),
    ({"body": "ok", "tags": "not-a-list"}, "Invalid tags"),
])
def test_share_import_enforces_limits(client, payload, error):
    response = client.post("/share/import", json=payload)
    assert response.status_code == 400
    assert response.get_json() == {"error": error}


def test_import_skips_oversized_stashes(client, user):
    export = {"stashes": [
        {"id": "too-big", "body": "x" * 50001},
        {"id": "fine", "body": "hello", "title": "ok"},
    ]}
    response = client.post(
        "/import",
        data={"file": (io.BytesIO(json.dumps(export).encode()), "export.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "1 were too long to keep." in response.get_data(as_text=True)
    assert [s.id for s in user.stashes] == ["fine"]


# Security headers ------------------------------------------------------------

def test_security_headers_present(app):
    response = app.test_client().get("/login")
    csp = response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_inline_scripts_carry_the_request_nonce(client):
    response = client.get("/pass")
    nonce = response.headers["Content-Security-Policy"].split("'nonce-")[1].split("'")[0]
    html = response.get_data(as_text=True)
    assert f'<script nonce="{nonce}">' in html
    # A fresh nonce on every request
    assert nonce not in client.get("/pass").headers["Content-Security-Policy"]


def test_templates_have_no_inline_event_handlers():
    import pathlib
    import re
    pattern = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
    offenders = [
        str(path) for path in pathlib.Path("templates").rglob("*.html")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_every_post_form_sends_a_csrf_token():
    import pathlib
    import re
    form_pattern = re.compile(r"<form\b[^>]*method=\"post\"[^>]*>(.*?)</form>", re.IGNORECASE | re.DOTALL)
    token_markers = ('name="csrf_token"', "form.csrf_token", "form.hidden_tag()")
    missing = []
    for path in pathlib.Path("templates").rglob("*.html"):
        for body in form_pattern.findall(path.read_text(encoding="utf-8")):
            if not any(marker in body for marker in token_markers):
                missing.append(f"{path}: {body.strip()[:60]}")
    assert missing == []


def test_hsts_only_with_secure_cookies(app, monkeypatch):
    assert "Strict-Transport-Security" not in app.test_client().get("/login").headers
    monkeypatch.setitem(app.config, "SESSION_COOKIE_SECURE", True)
    assert "Strict-Transport-Security" in app.test_client().get("/login").headers


# Error details and proxies ---------------------------------------------------

def test_readyz_does_not_leak_error_details(app, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("secret connection string")
    monkeypatch.setattr(db.session, "execute", broken)
    response = app.test_client().get("/readyz")
    assert response.status_code == 503
    assert response.get_json() == {"status": "error"}


def test_proxy_fix_uses_forwarded_client_ip(monkeypatch):
    monkeypatch.setattr(TestingConfig, "PROXY_FIX_COUNT", 1)
    app = create_app("testing")

    @app.route("/_ip")
    def _ip():
        from flask import request
        return request.remote_addr

    response = app.test_client().get("/_ip", headers={"X-Forwarded-For": "203.0.113.9"})
    assert response.get_data(as_text=True) == "203.0.113.9"


def test_forwarded_ip_ignored_without_proxy_fix(app):
    @app.route("/_ip")
    def _ip():
        from flask import request
        return request.remote_addr

    response = app.test_client().get("/_ip", headers={"X-Forwarded-For": "203.0.113.9"})
    assert response.get_data(as_text=True) != "203.0.113.9"
