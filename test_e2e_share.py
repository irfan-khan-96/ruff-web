"""
Browser end-to-end test of Nearby Share: one page sends a stash over WebRTC,
another receives and imports it.

Needs Playwright with Chromium (see requirements-dev.txt) and network access
for the Socket.IO client on cdnjs. Skipped when Playwright is not installed.
"""

import socket
import threading

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from app import create_app
from config import TestingConfig
from models import db, User, Stash
from sockets import socketio

PASSWORD = "correct-horse-battery"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """Run the app with Socket.IO on a real port, backed by a file database."""
    db_path = tmp_path_factory.mktemp("e2e") / "e2e.db"
    patch = pytest.MonkeyPatch()
    # Threads need a shared database; the testing default is per-connection memory
    patch.setattr(TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{db_path}")
    app = create_app("testing")
    patch.undo()

    with app.app_context():
        db.create_all()
        user = User(username="sharer", email="sharer@example.com", email_verified=True)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.flush()
        stash = Stash(title="Sent over WebRTC", body="Hello from the other tab", user_id=user.id)
        db.session.add(stash)
        db.session.commit()
        stash_id, user_id = stash.id, user.id

    port = _free_port()
    thread = threading.Thread(
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
    )
    thread.start()
    yield {"app": app, "url": f"http://127.0.0.1:{port}", "stash_id": stash_id, "user_id": user_id}


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except sync_api.Error as exc:
            pytest.skip(f"Chromium not installed for Playwright: {exc}")
        yield browser
        browser.close()


def test_nearby_share_sends_and_imports_a_stash(live_server, browser):
    url = live_server["url"]
    context = browser.new_context()
    csp_errors = []

    sender = context.new_page()
    sender.on("console", lambda msg: msg.type == "error" and csp_errors.append(msg.text))
    sender.goto(f"{url}/login")
    sender.fill("#username", "sharer")
    sender.fill("#password", PASSWORD)
    sender.click("#submit")
    sender.wait_for_url(f"{url}/")

    # Sender: open the stash's share page and start a session
    sender.goto(f"{url}/share/{live_server['stash_id']}")
    sender.click("#start-share")
    sync_api.expect(sender.locator("#share-code")).not_to_have_text("Code: —")
    code = sender.locator("#share-code").inner_text().removeprefix("Code: ").strip()
    assert len(code) == 6

    # Receiver: a second tab (same logged-in user) joins with the code
    receiver = context.new_page()
    receiver.on("console", lambda msg: msg.type == "error" and csp_errors.append(msg.text))
    receiver.goto(f"{url}/share")
    receiver.fill("#receive-code", code)
    receiver.click("#join-share")

    sync_api.expect(sender.locator("#share-status")).to_have_text("Stash sent.", timeout=15000)
    sync_api.expect(receiver.locator("#receive-status")).to_have_text(
        "Stash imported successfully.", timeout=15000
    )

    with live_server["app"].app_context():
        bodies = [s.body for s in Stash.query.filter_by(user_id=live_server["user_id"]).all()]
    assert bodies == ["Hello from the other tab", "Hello from the other tab"]

    # The CSP must not block anything the page needs
    assert [e for e in csp_errors if "Content Security Policy" in e] == []
    context.close()
