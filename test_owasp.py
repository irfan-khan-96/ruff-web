"""
Regression tests for the OWASP Top 10:2025 review (see SECURITY.md).

Grouped by category; earlier controls (secrets, tokens, headers, CSRF, size
limits) are covered in test_security.py.
"""

import logging

import pytest

import auth_utils
import routes
from app import create_app
from config import ProductionConfig, TestingConfig
from models import db, User, Stash
from conftest import sign_in



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
    db.session.add(user)
    db.session.commit()
    return user


def logged_in_client(app, username):
    return sign_in(app.test_client(), User.query.filter_by(username=username).first())


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
    ("get", "/export/stash/{id}"),
    ("post", "/stashes/{id}/delete"),
    ("post", "/relay/start/{id}"),
])
def test_other_users_stash_is_not_found(app, alice, bob_stash, method, path):
    client = logged_in_client(app, "alice")
    response = getattr(client, method)(path.format(id=bob_stash.id))
    assert response.status_code == 404
    assert db.session.get(Stash, bob_stash.id).body == "bob's secret"


def test_page_shells_never_contain_note_data(app, alice, bob_stash):
    """Notes reach a page only through the owner's sync, never in server HTML."""
    response = logged_in_client(app, "alice").get(f"/stashes/{bob_stash.id}")
    assert response.status_code == 200 and b"bob's secret" not in response.data


def test_old_nearby_share_links_redirect(app, alice, bob_stash):
    client = logged_in_client(app, "alice")
    assert client.get("/share").headers["Location"] == "/pass"
    assert client.get(f"/share/{bob_stash.id}").headers["Location"] == f"/stashes/{bob_stash.id}"
    assert client.get("/share/not-a-uuid").headers["Location"] == "/pass"


def test_sync_never_returns_or_accepts_other_users_notes(app, alice, bob_stash):
    import time
    client = logged_in_client(app, "alice")
    reply = client.post("/api/sync", json={"cursor": None, "changes": [
        {"id": bob_stash.id, "text": "mine now", "tags": [], "updated_at": int(time.time() * 1000)},
        {"id": bob_stash.id, "deleted": True, "updated_at": int(time.time() * 1000)},
    ]}, headers={"Accept": "application/json"}).get_json()
    assert [r["reason"] for r in reply["rejected"]] == ["not yours", "not yours"]
    assert reply["stashes"] == [] and reply["deleted"] == []
    assert db.session.get(Stash, bob_stash.id).body == "bob's secret"


def test_cannot_overwrite_other_users_stash(app, alice, bob_stash):
    client = logged_in_client(app, "alice")
    response = client.post("/stash", json={"text": "mine now", "stash_id": bob_stash.id},
                           headers={"Accept": "application/json"})
    assert response.status_code == 404
    assert db.session.get(Stash, bob_stash.id).body == "bob's secret"


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

def _link(sent, email):
    import re
    body = [message for message in sent if message[0] == email][-1][2]
    return re.search(r"https?://localhost(\S+)", body).group(1)


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(routes, "send_email", lambda to, subject, body: sent.append((to, subject, body)))
    return sent


def test_sign_in_does_not_reveal_who_has_an_account(app, alice, outbox):
    client = app.test_client()
    known = client.post("/login", data={"email": "ALICE@example.com"})
    unknown = client.post("/login", data={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 302
    assert known.headers["Location"] == unknown.headers["Location"] == "/login/sent"
    assert [to for to, _, _ in outbox] == ["alice@example.com", "nobody@example.com"]


def test_email_scanners_do_not_use_up_links(app, alice, outbox):
    """Opening (GET) a link only shows a button; signing in is a POST."""
    client = app.test_client()
    client.post("/login", data={"email": "alice@example.com"})
    link = _link(outbox, "alice@example.com")
    for _ in range(3):
        assert b"Sign me in" in app.test_client().get(link).data
    assert client.post(link).headers["Location"] == "/"


def test_links_work_once(app, alice, outbox):
    app.test_client().post("/login", data={"email": "alice@example.com"})
    link = _link(outbox, "alice@example.com")
    assert app.test_client().post(link).headers["Location"] == "/"
    assert app.test_client().post(link).headers["Location"] == "/login"
    # A sign-up link stops working once the account exists
    app.test_client().post("/login", data={"email": "new@example.com"})
    signup = _link(outbox, "new@example.com")
    assert app.test_client().post(signup).headers["Location"] == "/"
    assert app.test_client().post(signup).headers["Location"] == "/login"
    assert User.query.filter_by(email="new@example.com").count() == 1


def test_links_are_limited_per_address_across_ips(monkeypatch, outbox):
    monkeypatch.setattr(TestingConfig, "RATELIMIT_ENABLED", True, raising=False)
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        statuses = [
            app.test_client().post("/login", data={"email": "victim@example.com"},
                                   environ_base={"REMOTE_ADDR": f"198.51.100.{n}"}).status_code
            for n in range(11)
        ]
        assert statuses[:10] == [302] * 10 and statuses[10] == 429
        other = app.test_client().post("/login", data={"email": "someone@example.com"},
                                       environ_base={"REMOTE_ADDR": "198.51.100.200"})
        assert other.status_code == 302
        db.drop_all()


def test_old_password_routes_send_people_to_sign_in(app):
    client = app.test_client()
    for path in ["/signup", "/password/forgot", "/password/reset/abc", "/verify/abc", "/verify/resend"]:
        assert client.get(path).headers["Location"] == "/login", path


def test_viewing_login_page_does_not_count_against_limit(app):
    assert {app.test_client().get("/login").status_code for _ in range(15)} == {200}


# A09 Security Logging & Alerting Failures -------------------------------------

def test_unusable_sign_in_links_are_logged(app, caplog):
    with caplog.at_level(logging.WARNING, logger="ruff.security"):
        app.test_client().post("/auth/not-a-real-token")
    assert any("Unusable sign-in link (invalid)" in r.getMessage() for r in caplog.records)


def test_rate_limit_hits_are_logged(app, outbox, caplog):
    with caplog.at_level(logging.WARNING, logger="ruff.security"):
        client = app.test_client()
        statuses = [client.post("/login", data={"email": f"x{n}@example.com"}).status_code for n in range(6)]
    assert statuses[-1] == 429
    assert any("Rate limit hit: POST /login" in r.getMessage() for r in caplog.records)


def test_production_never_logs_email_bodies(app, monkeypatch, caplog):
    monkeypatch.setitem(app.config, "SMTP_HOST", "")
    monkeypatch.setattr(app, "debug", False)
    with app.test_request_context(), caplog.at_level(logging.DEBUG):
        auth_utils.send_email("alice@example.com", "Your Ruff sign-in link",
                              "Tap to sign in: https://ruff.example/auth/SECRET-TOKEN")
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
