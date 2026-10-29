"""
Regression tests for the OWASP Top 10:2025 review (see SECURITY.md).

Grouped by category; earlier controls (secrets, tokens, headers, CSRF, size
limits, Socket.IO auth) are covered in test_security.py.
"""

import logging

import pytest

import auth_utils
import routes
from app import create_app
from config import ProductionConfig, TestingConfig
from models import db, User, Stash
from sockets import socketio, MAX_JOINS_PER_MINUTE

PASSWORD = "correct-horse-battery"


@pytest.fixture
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def make_user(username):
    user = User(username=username, email=f"{username}@example.com", email_verified=True)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


def logged_in_client(app, username):
    client = app.test_client()
    assert client.post("/login", data={"username": username, "password": PASSWORD}).status_code == 302
    return client


@pytest.fixture
def alice(app):
    return make_user("alice")


@pytest.fixture
def bob_stash(app):
    bob = make_user("bob")
    stash = Stash(body="bob's secret", user_id=bob.id)
    db.session.add(stash)
    db.session.commit()
    return stash


# A01 Broken Access Control ---------------------------------------------------

@pytest.mark.parametrize("method, path", [
    ("get", "/stashes/{id}"),
    ("get", "/export/stash/{id}"),
    ("get", "/share/{id}"),
    ("get", "/share/payload/{id}"),
    ("post", "/stashes/{id}/delete"),
    ("post", "/relay/start/{id}"),
])
def test_other_users_stash_is_not_found(app, alice, bob_stash, method, path):
    client = logged_in_client(app, "alice")
    response = getattr(client, method)(path.format(id=bob_stash.id))
    assert response.status_code == 404
    assert db.session.get(Stash, bob_stash.id).body == "bob's secret"


def test_cannot_overwrite_other_users_stash(app, alice, bob_stash):
    client = logged_in_client(app, "alice")
    response = client.post("/stash", json={"text": "mine now", "stash_id": bob_stash.id},
                           headers={"Accept": "application/json"})
    assert response.status_code == 404
    assert db.session.get(Stash, bob_stash.id).body == "bob's secret"


def test_share_room_holds_only_sender_and_receiver(app, alice):
    make_user("mallory")
    sender = socketio.test_client(app, flask_test_client=logged_in_client(app, "alice"))
    receiver = socketio.test_client(app, flask_test_client=logged_in_client(app, "alice"))
    intruder = socketio.test_client(app, flask_test_client=logged_in_client(app, "mallory"))
    for client in (sender, receiver):
        client.emit("join_room", {"room": "ROOM01"})
    intruder.get_received()

    intruder.emit("join_room", {"room": "ROOM01"})
    assert [(m["name"], m["args"][0]) for m in intruder.get_received()] == [
        ("join_refused", {"reason": "room_full"})
    ]
    # And nobody in the room heard about the intruder
    sender.get_received()
    receiver.emit("signal", {"room": "ROOM01", "payload": {"type": "offer"}})
    assert [m["name"] for m in sender.get_received()] == ["signal"]
    assert intruder.get_received() == []


def test_signal_requires_room_membership(app, alice):
    member = socketio.test_client(app, flask_test_client=logged_in_client(app, "alice"))
    outsider = socketio.test_client(app, flask_test_client=logged_in_client(app, "alice"))
    member.emit("join_room", {"room": "ROOM02"})
    member.get_received()

    outsider.emit("signal", {"room": "ROOM02", "payload": {"type": "offer", "evil": True}})
    assert member.get_received() == []


def test_share_code_guessing_is_throttled(app, alice):
    guesser = socketio.test_client(app, flask_test_client=logged_in_client(app, "alice"))
    for n in range(MAX_JOINS_PER_MINUTE):
        guesser.emit("join_room", {"room": f"G{n:05d}"})
    guesser.get_received()
    guesser.emit("join_room", {"room": "GUESS9"})
    assert [(m["name"], m["args"][0]) for m in guesser.get_received()] == [
        ("join_refused", {"reason": "too_many_attempts"})
    ]


# A04 Cryptographic Failures ----------------------------------------------------

def test_production_requires_long_secrets(monkeypatch):
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "x" * 31)
    monkeypatch.setattr(ProductionConfig, "SECURITY_PASSWORD_SALT", "y" * 64)
    with pytest.raises(RuntimeError, match="at least 32"):
        create_app("production")


# A05 Injection -----------------------------------------------------------------

def test_export_filename_is_sanitised(app, alice):
    # The download name comes from the first line (the title)
    stash = Stash(body='Plans: X-Injected: 1 "../../etc"\r\nbody', user_id=alice.id)
    db.session.add(stash)
    db.session.commit()
    response = logged_in_client(app, "alice").get(f"/export/stash/{stash.id}")
    assert response.status_code == 200
    disposition = response.headers["Content-Disposition"]
    assert "X-Injected" not in response.headers
    assert all(ch not in disposition for ch in "\r\n/") and "stash-Plans-X-Injected-1-etc.txt" in disposition


# A07 Authentication Failures ----------------------------------------------------

@pytest.mark.parametrize("password, accepted", [
    ("seven77", False),
    ("x" * 129, False),
    ("eight888", True),
])
def test_password_policy(app, password, accepted):
    response = app.test_client().post("/signup", data={
        "username": "newuser", "email": "new@example.com",
        "password": password, "confirm_password": password,
    })
    assert (User.query.filter_by(username="newuser").first() is not None) == accepted
    if not accepted:
        assert b"between 8 and 128 characters" in response.data


def test_unknown_username_costs_a_password_hash(app, alice, monkeypatch):
    """Unknown usernames must not answer faster (timing-based user enumeration)."""
    calls = []
    real_check = routes.check_password_hash
    monkeypatch.setattr(routes, "check_password_hash",
                        lambda pwhash, password: calls.append(1) or real_check(pwhash, password))
    app.test_client().post("/login", data={"username": "no-such-user", "password": "whatever-1"})
    assert calls == [1]


def test_signup_does_not_reveal_registered_emails(app, alice, monkeypatch):
    sent = []
    monkeypatch.setattr(routes, "send_email", lambda to, subject, body: sent.append((to, subject)))
    response = app.test_client().post("/signup", data={
        "username": "copycat", "email": "ALICE@example.com",
        "password": PASSWORD, "confirm_password": PASSWORD,
    }, follow_redirects=True)
    # Same answer as a successful sign-up; no second account; the owner is told
    assert b"Almost there. Check your email" in response.data
    assert User.query.filter_by(username="copycat").first() is None
    assert sent == [("alice@example.com", "Someone tried to sign up with your email")]


def test_login_is_limited_per_account_across_ips(monkeypatch, alice):
    monkeypatch.setattr(TestingConfig, "RATELIMIT_ENABLED", True, raising=False)
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        make_user("victim")
        statuses = [
            app.test_client().post(
                "/login", data={"username": "victim", "password": f"guess-{n}"},
                environ_base={"REMOTE_ADDR": f"198.51.100.{n}"},
            ).status_code
            for n in range(21)
        ]
        assert statuses[:20] == [302] * 20 and statuses[20] == 429
        # Other accounts are unaffected
        other = app.test_client().post("/login", data={"username": "someone-else", "password": "x"},
                                       environ_base={"REMOTE_ADDR": "198.51.100.200"})
        assert other.status_code == 302
        db.drop_all()


def test_viewing_login_page_does_not_count_against_limit(app):
    assert {app.test_client().get("/login").status_code for _ in range(15)} == {200}


# A09 Security Logging & Alerting Failures -------------------------------------

def test_failed_login_is_logged(app, alice, caplog):
    with caplog.at_level(logging.WARNING, logger="ruff.security"):
        app.test_client().post("/login", data={"username": "alice", "password": "wrong-password"})
    assert any("Failed login for username='alice'" in r.getMessage() for r in caplog.records)
    assert not any(PASSWORD in r.getMessage() or "wrong-password" in r.getMessage() for r in caplog.records)


def test_rate_limit_hits_are_logged(app, caplog):
    with caplog.at_level(logging.WARNING, logger="ruff.security"):
        client = app.test_client()
        statuses = [client.post("/login", data={"username": "x", "password": "y"}).status_code
                    for _ in range(11)]
    assert statuses[-1] == 429
    assert any("Rate limit hit: POST /login" in r.getMessage() for r in caplog.records)


def test_production_never_logs_email_bodies(app, monkeypatch, caplog):
    monkeypatch.setitem(app.config, "SMTP_HOST", "")
    monkeypatch.setattr(app, "debug", False)
    with app.test_request_context(), caplog.at_level(logging.DEBUG):
        auth_utils.send_email("alice@example.com", "Reset your Ruff password",
                              "Reset your password: https://ruff.example/password/reset/SECRET-TOKEN")
    assert "SECRET-TOKEN" not in caplog.text
    assert "not sent" in caplog.text


def test_sentry_only_starts_with_a_dsn(monkeypatch):
    import sentry_sdk
    started = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: started.append(kwargs))
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "k" * 64)
    monkeypatch.setattr(ProductionConfig, "SECURITY_PASSWORD_SALT", "s" * 64)

    monkeypatch.delenv("SENTRY_DSN", raising=False)
    create_app("production")
    assert started == []

    monkeypatch.setenv("SENTRY_DSN", "https://key@sentry.example/1")
    create_app("production")
    assert started[0]["dsn"] == "https://key@sentry.example/1"
    assert started[0]["send_default_pii"] is False


# A10 Mishandling of Exceptional Conditions -------------------------------------

def test_not_found_is_not_swallowed_by_error_handling(app, alice):
    client = logged_in_client(app, "alice")
    for path in ["/stashes/does-not-exist", "/export/stash/does-not-exist"]:
        assert client.get(path).status_code == 404, path
    assert client.post("/stash", json={"text": "x", "stash_id": "does-not-exist"},
                       headers={"Accept": "application/json"}).status_code == 404
