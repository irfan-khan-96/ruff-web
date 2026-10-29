"""
Browser end-to-end tests of Ruff's main flows: accounts, stashes and their
task notes, collections and bulk actions, export/import, and Recess Relay.

Run against the real app with CSRF on (see conftest.py). Skipped when
Playwright is not installed.
"""

import json
import re

from conftest import PASSWORD, login, sync_api

expect = sync_api.expect if sync_api else None


def _link_from(email):
    return re.search(r"https?://\S+", email["body"]).group(0)


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
    expect(page.locator("body")).to_contain_text("Check your email to verify")

    # Unverified accounts can't log in yet
    page.fill("#username", username)
    page.fill("#password", PASSWORD)
    page.click("#submit")
    expect(page.locator("body")).to_contain_text("Please verify your email")

    email = live_server.outbox[-1]
    assert email["to"] == f"{username}@example.com"
    page.goto(_link_from(email))
    expect(page.locator("body")).to_contain_text("Email verified")

    login(page, live_server, username)
    expect(page.locator(".nav-username")).to_have_text(username)


def test_password_reset_and_old_password_stops_working(live_server, new_page):
    username = live_server.create_user("forgetful")
    page = new_page()
    page.goto(f"{live_server.url}/password/forgot")
    page.fill("#email", f"{username}@example.com")
    page.click("#submit")
    expect(page.locator("body")).to_contain_text("a reset link has been sent")

    page.goto(_link_from(live_server.outbox[-1]))
    page.fill("#password", "a-brand-new-password")
    page.fill("#confirm_password", "a-brand-new-password")
    page.click("#submit")
    expect(page.locator("body")).to_contain_text("Password reset successfully")

    page.fill("#username", username)
    page.fill("#password", PASSWORD)
    page.click("#submit")
    expect(page.locator("body")).to_contain_text("Invalid username or password")
    login(page, live_server, username, "a-brand-new-password")


def test_logout_ends_the_session(live_server, new_page):
    page = new_page()
    login(page, live_server, live_server.create_user())
    page.click(".logout-link")
    expect(page.locator("body")).to_contain_text("You have been logged out")
    page.goto(f"{live_server.url}/stashes")
    expect(page).to_have_url(re.compile(r"/login$"))


# Stashes -----------------------------------------------------------------------

def test_stash_lifecycle_with_task_note(live_server, new_page):
    page = new_page()
    login(page, live_server, live_server.create_user())

    # Create, with two tasks on the task note (first one ticked)
    page.fill("#title", "Weekend plans")
    page.fill("#body", "Picnic if it is sunny")
    page.click("[data-note-toggle]")
    tasks = page.locator("[data-checklist-items] input[type=text]")
    tasks.nth(0).fill("Buy bread")
    tasks.nth(0).press("Enter")
    tasks.nth(1).fill("Pack blanket")
    page.locator("[data-checklist-items] input[type=checkbox]").nth(0).check()
    page.click("#submit")
    expect(page.locator("body")).to_contain_text("Stash saved successfully")

    # Listed and searchable
    page.goto(f"{live_server.url}/stashes")
    expect(page.locator(".stash-card")).to_have_count(1)
    page.fill("input[name=search]", "picnic")
    page.click(".btn-search")
    expect(page.locator(".stash-card")).to_have_count(1)
    page.fill("input[name=search]", "no-such-text")
    page.click(".btn-search")
    expect(page.locator(".stash-card")).to_have_count(0)

    # View shows the task note with the right ticks
    page.goto(f"{live_server.url}/stashes")
    page.locator(".stash-item", has_text="Weekend plans").locator("text=View").click()
    items = page.locator(".sticky-checklist li")
    expect(items).to_have_count(2)
    expect(items.nth(0).locator("input")).to_be_checked()
    expect(items.nth(1).locator("input")).not_to_be_checked()

    # Edit
    page.click("text=Edit")
    page.fill("#title", "Weekend plans (rain)")
    page.click("text=Update Stash")
    expect(page.locator("body")).to_contain_text("Stash updated successfully")
    expect(page.locator("body")).to_contain_text("Weekend plans (rain)")

    # Delete
    page.locator(".delete-form button").first.click()
    expect(page.locator("body")).to_contain_text("Stash deleted successfully")
    expect(page.locator(".stash-card")).to_have_count(0)


def test_collections_and_bulk_actions(live_server, new_page):
    from models import db, Stash, User

    username = live_server.create_user()

    def seed():
        user = User.query.filter_by(username=username).first()
        db.session.add_all([Stash(title=f"Note {i}", body=f"body {i}", user_id=user.id) for i in range(3)])
        db.session.commit()

    live_server.query(seed)
    page = new_page()
    login(page, live_server, username)

    # Create a collection
    page.goto(f"{live_server.url}/collections/new")
    page.fill("#name", "School")
    page.fill("#description", "Homework and notes")
    page.click("#submit")
    expect(page.locator("body")).to_contain_text("Collection 'School' created")

    # Bulk-move two stashes into it, then filter by it
    page.goto(f"{live_server.url}/stashes")
    page.locator(".stash-select").nth(0).check()
    page.locator(".stash-select").nth(1).check()
    with page.expect_navigation():
        page.select_option("#bulk-move-to", label="School")
    page.locator(".filter-link", has_text="School").click()
    expect(page.locator(".stash-card")).to_have_count(2)

    # Bulk delete those two (the bar appears once something is selected)
    page.locator(".stash-select").nth(0).check()
    page.click("#select-all-btn")
    page.once("dialog", lambda dialog: dialog.accept())
    with page.expect_navigation():
        page.click("#bulk-delete-btn")
    page.goto(f"{live_server.url}/stashes")
    expect(page.locator(".stash-card")).to_have_count(1)

    # Deleting the collection asks first; cancelling keeps it
    page.goto(f"{live_server.url}/collections")
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.click("button[data-confirm]")
    expect(page.locator("body")).to_contain_text("School")
    page.once("dialog", lambda dialog: dialog.accept())
    page.click("button[data-confirm]")
    expect(page.locator("body")).to_contain_text("Collection 'School' deleted")


def test_export_then_import_restores_stashes(live_server, new_page, tmp_path):
    from models import db, Stash, User

    username = live_server.create_user()

    def seed():
        user = User.query.filter_by(username=username).first()
        db.session.add(Stash(title="Keep me", body="Precious notes", user_id=user.id,
                             checklist=[{"text": "step one", "done": True}]))
        db.session.commit()

    live_server.query(seed)
    page = new_page()
    login(page, live_server, username)

    # Export everything
    with page.expect_download() as download_info:
        page.goto(f"{live_server.url}/stashes")
        page.evaluate("url => { window.location.href = url }", f"{live_server.url}/export")
    export_path = tmp_path / "export.json"
    download_info.value.save_as(export_path)
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert [s["title"] for s in exported["stashes"]] == ["Keep me"]

    # Delete it, then import the export back
    page.goto(f"{live_server.url}/stashes")
    page.locator(".delete-form button").first.click()
    expect(page.locator(".stash-card")).to_have_count(0)

    page.goto(f"{live_server.url}/import")
    page.set_input_files("#file-input", str(export_path))
    page.click("button[type=submit].btn-primary")
    expect(page.locator("body")).to_contain_text("Import successful")
    expect(page.locator(".stash-card")).to_have_count(1)
    expect(page.locator("body")).to_contain_text("Keep me")


# Recess Relay ------------------------------------------------------------------

def test_relay_owner_and_guest(live_server, new_page):
    owner = new_page()
    login(owner, live_server, live_server.create_user("host"))

    owner.goto(f"{live_server.url}/relay")
    owner.fill("#relay-title", "Story time")
    owner.fill("#relay-prompt", "Once upon a recess")
    owner.fill("#relay-max", "3")
    owner.click("text=Start Relay")
    expect(owner.locator("body")).to_contain_text("Relay started")
    code = owner.url.rstrip("/").split("/")[-1]

    # A logged-out guest joins by code and adds a line under a name
    guest = new_page()
    guest.goto(f"{live_server.url}/relay")
    guest.fill("#relay-code", code.lower())
    guest.click("text=Join Relay")
    expect(guest.locator("body")).to_contain_text("Once upon a recess")
    guest.fill("#relay-author", "Visitor")
    guest.fill("#relay-body", "a dragon joined the game")
    guest.click("text=Pass it on")
    expect(guest.locator("body")).to_contain_text("a dragon joined the game")

    # Guests can't close it; the owner can, after which no more lines
    expect(guest.locator("text=Close Relay")).to_have_count(0)
    owner.reload()
    expect(owner.locator("body")).to_contain_text("Visitor")
    owner.click("text=Close Relay")
    expect(owner.locator("body")).to_contain_text("Relay closed")
    guest.reload()
    expect(guest.locator("#relay-body")).to_have_count(0)
    expect(guest.locator("body")).to_contain_text("This relay is closed")
