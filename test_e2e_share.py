"""
Browser end-to-end test of Nearby Share: one tab sends a stash over WebRTC,
another receives and imports it.

Needs Playwright with Chromium (see requirements-dev.txt) and network access
for the Socket.IO client on cdnjs. Skipped when Playwright is not installed.
"""

from conftest import login, sync_api


def test_nearby_share_sends_and_imports_a_stash(live_server, new_page):
    from models import db, Stash, User

    username = live_server.create_user("sharer")

    def seed():
        user = User.query.filter_by(username=username).first()
        stash = Stash(title="Sent over WebRTC", body="Hello from the other tab", user_id=user.id)
        db.session.add(stash)
        db.session.commit()
        return stash.id, user.id

    stash_id, user_id = live_server.query(seed)

    sender = new_page()
    login(sender, live_server, username)

    # Sender: open the stash's share page and start a session
    sender.goto(f"{live_server.url}/share/{stash_id}")
    sender.click("#start-share")
    sync_api.expect(sender.locator("#share-code")).not_to_have_text("Code: —")
    code = sender.locator("#share-code").inner_text().removeprefix("Code: ").strip()
    assert len(code) == 6

    # Receiver: a second tab of the same session joins with the code
    receiver = sender.context.new_page()
    receiver.goto(f"{live_server.url}/share")
    receiver.fill("#receive-code", code)
    receiver.click("#join-share")

    sync_api.expect(sender.locator("#share-status")).to_have_text("Stash sent.", timeout=15000)
    sync_api.expect(receiver.locator("#receive-status")).to_have_text(
        "Stash imported successfully.", timeout=15000
    )

    bodies = live_server.query(
        lambda: [s.body for s in Stash.query.filter_by(user_id=user_id).all()]
    )
    # The copy is the same sheet (title line included once, not duplicated)
    assert bodies == ["Sent over WebRTC\n\nHello from the other tab"] * 2
