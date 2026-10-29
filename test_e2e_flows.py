"""
Browser end-to-end tests of the main flows: accounts, the sheet (write, stash,
autosave, Recess Roster), the stash list, tossing, backups and Recess Relay.

Run against the real app with CSRF on (see conftest.py). Skipped when
Playwright is not installed.
"""

import json
import re

from conftest import PASSWORD, login, sync_api

expect = sync_api.expect if sync_api else None


def _link_from(email):
    return re.search(r"https?://\S+", email["body"]).group(0)


def _seed(live_server, username, notes):
    """Give a user some stashes: [(text, [tags]), ...]."""
    from models import db, Stash, User

    def seed():
        user = User.query.filter_by(username=username).first()
        for text, tags in notes:
            item = Stash(body=text, user_id=user.id)
            db.session.add(item)
            db.session.flush()
            for tag in tags:
                item.add_tag(tag)
        db.session.commit()

    live_server.query(seed)


# Accounts ----------------------------------------------------------------------

def test_signup_verify_email_and_log_in(live_server, new_page):
    page = new_page()
    username = "newbie" + str(len(live_server.outbox))
    page.goto(f"{live_server.url}/signup")
    page.fill("#username", username)
    page.fill("#email", f"{username}@example.com")
    page.fill("#password", PASSWORD)
    page.fill("#confirm_password", PASSWORD)
    page.click("#submit")
    expect(page.locator(".toast")).to_contain_text("Check your email to verify")

    # Unverified accounts can't log in yet
    page.fill("#username", username)
    page.fill("#password", PASSWORD)
    page.click("#submit")
    expect(page.locator(".toast")).to_contain_text("verify your account first")

    email = live_server.outbox[-1]
    assert email["to"] == f"{username}@example.com"
    page.goto(_link_from(email))
    expect(page.locator(".toast")).to_contain_text("Email verified")

    login(page, live_server, username)
    expect(page.locator(".toast")).to_contain_text(f"Welcome back, {username}")


def test_password_reset_and_old_password_stops_working(live_server, new_page):
    username = live_server.create_user("forgetful")
    page = new_page()
    page.goto(f"{live_server.url}/password/forgot")
    page.fill("#email", f"{username}@example.com")
    page.click("#submit")
    expect(page.locator(".toast")).to_contain_text("a reset link is on its way")

    page.goto(_link_from(live_server.outbox[-1]))
    page.fill("#password", "a-brand-new-password")
    page.fill("#confirm_password", "a-brand-new-password")
    page.click("#submit")
    expect(page.locator(".toast")).to_contain_text("Password changed")

    page.fill("#username", username)
    page.fill("#password", PASSWORD)
    page.click("#submit")
    expect(page.locator(".toast")).to_contain_text("don't match")
    login(page, live_server, username, "a-brand-new-password")


def test_log_out_from_the_lounge(live_server, new_page):
    page = new_page()
    login(page, live_server, live_server.create_user())
    page.goto(f"{live_server.url}/lounge")
    page.click("text=Log out")
    expect(page.locator(".toast")).to_contain_text("Logged out")
    page.goto(f"{live_server.url}/stashes")
    expect(page).to_have_url(re.compile(r"/login$"))


# The sheet -----------------------------------------------------------------------

def test_write_before_signing_up_keeps_the_draft(live_server, new_page):
    page = new_page()
    page.goto(live_server.url + "/")
    page.fill("#sheet-text", "Things to bring tomorrow")
    expect(page.locator("#sheet-status")).to_contain_text("Kept on this device")
    expect(page.get_by_role("link", name="Sign up to stash")).to_be_visible()

    page.reload()
    expect(page.locator("#sheet-text")).to_have_value("Things to bring tomorrow")
    expect(page.locator("#sheet-status")).to_contain_text("Picked up where you left off")


def test_sheet_lists_roster_and_stashing(live_server, new_page):
    from models import Stash, User

    username = live_server.create_user()
    page = new_page()
    login(page, live_server, username)
    text = page.locator("#sheet-text")

    # Type a title, then a task list using the To-do button and Enter to continue it
    text.click()
    text.type("Kickball plan")
    page.click("#roster-add")
    text.type("Find the ball")
    text.press("Enter")
    text.type("Ask for the field")
    text.press("Enter")
    text.press("Enter")  # an empty item ends the list
    text.type("Pick teams fairly")
    expect(text).to_have_value("Kickball plan\n[ ] Find the ball\n[ ] Ask for the field\nPick teams fairly")

    # The Recess Roster mirrors the tasks; ticking one edits the text
    roster = page.locator("#roster-list li")
    expect(roster).to_have_count(2)
    roster.nth(0).locator("input").check()
    expect(text).to_have_value(re.compile(r"\[x\] Find the ball"))
    expect(page.locator("#word-count")).to_contain_text("words")

    # Stash with the keyboard shortcut: it opens as a stash
    page.fill("#sheet-tags", "Recess, #team")
    text.press("Control+s")
    page.wait_for_url(re.compile(r"/stashes/[0-9a-f-]{36}$"))
    expect(page.locator(".toast")).to_contain_text("Stashed.")
    stash_id = page.url.rsplit("/", 1)[1]

    # Edits autosave without pressing anything
    text.click()
    text.press("End")
    text.type("\nBring water")
    expect(page.locator("#sheet-status")).to_contain_text("Stashed · just now", timeout=8000)

    def stored():
        item = Stash.query.filter_by(id=stash_id).first()
        return item.title, item.body, sorted(t.name for t in item.tags), item.user.username

    title, body, tags, owner = live_server.query(stored)
    assert (title, tags, owner) == ("Kickball plan", ["recess", "team"], username)
    assert "[x] Find the ball" in body and body.endswith("Bring water")


def test_stash_list_search_tags_and_toss(live_server, new_page):
    username = live_server.create_user()
    _seed(live_server, username, [
        ("Field trip\nBring lunch", ["trips"]),
        ("Science fair\nA model of the jungle gym", ["school"]),
        ("Swing schedule", []),
    ])
    page = new_page()
    login(page, live_server, username)
    page.goto(f"{live_server.url}/stashes")
    expect(page.locator(".stash-card")).to_have_count(3)

    page.fill("#search", "jungle")
    page.get_by_role("button", name="Search").click()
    expect(page.locator(".stash-card")).to_have_count(1)
    expect(page.locator(".stash-card-title")).to_have_text("Science fair")

    page.goto(f"{live_server.url}/stashes")
    page.click(".chip >> text=#trips")
    expect(page.locator(".stash-card")).to_have_count(1)

    # Open it, then toss it: cancelling keeps it, confirming removes it
    page.click(".stash-card")
    expect(page.locator("#sheet-text")).to_have_value("Field trip\nBring lunch")
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.click("text=Toss it")
    expect(page.locator("#sheet-text")).to_be_visible()
    page.once("dialog", lambda dialog: dialog.accept())
    page.click("text=Toss it")
    expect(page.locator(".toast")).to_contain_text("Tossed it.")
    expect(page.locator(".stash-card")).to_have_count(2)


def test_backup_then_restore(live_server, new_page, tmp_path):
    username = live_server.create_user()
    _seed(live_server, username, [("Keep me\n[x] step one", ["safe"])])
    page = new_page()
    login(page, live_server, username)

    page.goto(f"{live_server.url}/lounge")
    with page.expect_download() as download_info:
        page.click("text=Download backup")
    backup = tmp_path / "backup.json"
    download_info.value.save_as(backup)
    assert [s["title"] for s in json.loads(backup.read_text(encoding="utf-8"))["stashes"]] == ["Keep me"]

    page.goto(f"{live_server.url}/stashes")
    page.click(".stash-card")
    page.once("dialog", lambda dialog: dialog.accept())
    page.click("text=Toss it")
    expect(page.locator(".stash-card")).to_have_count(0)

    page.goto(f"{live_server.url}/lounge")
    page.set_input_files("#file-input", str(backup))
    page.get_by_role("button", name="Restore", exact=True).click()
    expect(page.locator(".toast")).to_contain_text("Restored 1 stash.")
    expect(page.locator(".stash-card-title")).to_have_text("Keep me")


# Recess Relay ------------------------------------------------------------------

def test_relay_owner_and_guest(live_server, new_page):
    owner = new_page()
    login(owner, live_server, live_server.create_user("host"))

    owner.goto(f"{live_server.url}/pass")
    owner.fill("#relay-title-input", "Story time")
    owner.fill("#relay-prompt", "Once upon a recess")
    owner.fill("#relay-max", "3")
    owner.click("text=Start a relay")
    expect(owner.locator(".toast")).to_contain_text("Relay started")
    code = owner.url.rstrip("/").split("/")[-1]

    # A logged-out guest joins by code and adds a line under a name
    guest = new_page()
    guest.goto(f"{live_server.url}/pass")
    guest.fill("#relay-code", code.lower())
    guest.click("button:has-text('Join')")
    expect(guest.locator(".relay-prompt")).to_have_text("Once upon a recess")
    guest.fill("#relay-author", "Visitor")
    guest.fill("#relay-body", "a dragon joined the game")
    guest.click("text=Pass it on")
    expect(guest.locator(".relay-line")).to_contain_text("a dragon joined the game")

    # Guests can't close it; the owner can, after which no more lines
    expect(guest.locator("text=Close relay")).to_have_count(0)
    owner.reload()
    expect(owner.locator(".relay-author")).to_have_text("Visitor")
    owner.once("dialog", lambda dialog: dialog.accept())
    owner.click("text=Close relay")
    expect(owner.locator(".toast")).to_contain_text("Relay closed")
    guest.reload()
    expect(guest.locator("#relay-body")).to_have_count(0)
    expect(guest.locator("text=This relay is closed.")).to_be_visible()
