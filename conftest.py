"""
Shared fixtures for the browser end-to-end tests (test_e2e_*.py).

They run the real app (Socket.IO included) on a free port with a file
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

PASSWORD = "correct-horse-battery"


class LiveServer:
    """Handle on the running app: its URL, captured emails and DB helpers."""

    def __init__(self, app, url, outbox):
        self.app = app
        self.url = url
        self.outbox = outbox

    def create_user(self, prefix="user", verified=True):
        """Create a user with PASSWORD and return its (unique) username."""
        from models import db, User
        username = f"{prefix}{uuid.uuid4().hex[:6]}"
        with self.app.app_context():
            user = User(username=username, email=f"{username}@example.com", email_verified=verified)
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.commit()
        return username

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
    from sockets import socketio

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
    threading.Thread(
        target=socketio.run,
        args=(app,),
        kwargs={
            "host": "127.0.0.1",
            "port": port,
            "allow_unsafe_werkzeug": True,
            "use_reloader": False,  # the reloader only works on the main thread
            "log_output": False,
        },
        daemon=True,
    ).start()
    yield LiveServer(app, f"http://127.0.0.1:{port}", outbox)
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


def login(page, server, username, password=PASSWORD):
    page.goto(f"{server.url}/login")
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#submit")
    page.wait_for_url(f"{server.url}/")
