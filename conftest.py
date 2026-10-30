"""
Shared fixtures for the browser end-to-end tests (test_e2e_*.py).

They run the real app on a free port with a file
database and drive it with Playwright's Chromium. They are skipped when
Playwright or its browser isn't installed; see requirements-dev.txt.
"""

import socket
import threading
import uuid

import pytest

try:
    from playwright import sync_api
except ImportError:  # pragma: no cover - depends on the environment
    sync_api = None



class LiveServer:
    """Handle on the running app: its URL, captured emails and DB helpers."""

    def __init__(self, app, url, outbox):
        self.app = app
        self.url = url
        self.outbox = outbox

    def create_user(self, prefix="user"):
        """Create a user (email <username>@example.com) and return its unique username."""
        from models import db, User
        username = f"{prefix}{uuid.uuid4().hex[:6]}"
        with self.app.app_context():
            db.session.add(User(username=username, email=f"{username}@example.com", email_verified=True))
            db.session.commit()
        return username

    def link_for(self, email):
        """The most recent sign-in link emailed to `email`."""
        import re
        for message in reversed(self.outbox):
            if message["to"] == email:
                return re.search(r"https?://\S+", message["body"]).group(0)
        raise AssertionError(f"no email to {email}")

    def query(self, fn):
        """Run fn() inside an app context (for checking database state)."""
        with self.app.app_context():
            return fn()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(tmp_path_factory):
    if sync_api is None:
        pytest.skip("Playwright is not installed (pip install -r requirements-dev.txt)")

    from app import create_app
    from config import TestingConfig
    from models import db
    import routes
    from werkzeug.serving import make_server

    patch = pytest.MonkeyPatch()
    # Threads need a shared database; the testing default is per-connection memory
    db_path = tmp_path_factory.mktemp("e2e") / "e2e.db"
    patch.setattr(TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{db_path}")
    # Exercise the real forms, CSRF tokens included
    patch.setattr(TestingConfig, "WTF_CSRF_ENABLED", True)
    # Many logins from one IP across tests would trip the login rate limit
    patch.setattr(TestingConfig, "RATELIMIT_ENABLED", False, raising=False)
    app = create_app("testing")
    patch.undo()

    # Capture outgoing email (verification / reset links) instead of sending it
    outbox = []
    patch.setattr(routes, "send_email", lambda to, subject, body: outbox.append(
        {"to": to, "subject": subject, "body": body}
    ))

    with app.app_context():
        db.create_all()

    port = _free_port()
    server = make_server("127.0.0.1", port, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield LiveServer(app, f"http://127.0.0.1:{port}", outbox)
    server.shutdown()
    patch.undo()


@pytest.fixture(scope="session")
def browser():
    if sync_api is None:
        pytest.skip("Playwright is not installed (pip install -r requirements-dev.txt)")
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except sync_api.Error as exc:
            pytest.skip(f"Chromium not installed for Playwright: {exc}")
        yield browser
        browser.close()


@pytest.fixture
def new_page(browser):
    """
    Factory for pages in fresh browser contexts (separate cookies = separate
    users). Fails the test if the Content-Security-Policy blocked anything.
    """
    contexts, csp_errors = [], []

    def make(**context_options):
        context = browser.new_context(**context_options)
        contexts.append(context)
        page = context.new_page()
        page.on("console", lambda msg: msg.type == "error"
                and "Content Security Policy" in msg.text and csp_errors.append(msg.text))
        page.set_default_timeout(10000)
        return page

    yield make
    for context in contexts:
        context.close()
    assert csp_errors == [], f"CSP blocked resources: {csp_errors}"


def login(page, server, username):
    """Sign in the passwordless way: request a link, open it, confirm."""
    email = f"{username}@example.com"
    page.goto(f"{server.url}/login")
    page.fill("#email", email)
    page.click("#submit")
    page.wait_for_url(f"{server.url}/login/sent")
    page.goto(server.link_for(email))
    page.click("#submit")
    page.wait_for_url(f"{server.url}/")
    page.wait_for_function("window.RuffStore && true")


def sign_in(client, user):
    """Unit tests: give a Flask test client a signed-in session for `user`."""
    from auth_utils import session_fingerprint
    with client.session_transaction() as sess:
        sess["user_id"] = user.id
        sess["epoch"] = session_fingerprint(user)
        sess.permanent = True
    return client
