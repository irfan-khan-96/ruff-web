"""
Browser end-to-end tests of the main flows: passwordless sign-in, the
local-first sheet (works signed out and offline, syncs across devices),
folded notes, the stash list, backups and Recess Relay.

Run against the real app with CSRF on (see conftest.py). Skipped when
Playwright is not installed.
"""

import json
import re
import time

from conftest import login, sync_api

expect = sync_api.expect if sync_api else None


def _eventually(fn, timeout=10):
    """Poll fn() until it returns something truthy (server state after a sync)."""
    end = time.time() + timeout
    while time.time() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.2)
    return fn()


def _stash(page, text, tags=""):
    """Write a note on a fresh sheet and stash it; returns its id."""
    page.goto(page.url.split("/", 3)[0] + "//" + page.url.split("/", 3)[2] + "/")
    page.fill("#sheet-text", text)
    if tags:
        page.fill("#sheet-tags", tags)
    page.click("#stash-button")
    page.wait_for_url(re.compile(r"/stashes/[0-9a-f-]{36}$"))
    return page.url.rsplit("/", 1)[1]


def _server_note(live_server, note_id):
    from models import Stash
    return live_server.query(lambda: (lambda s: s and (s.body, sorted(t.name for t in s.tags), s.user.username))(
        Stash.query.filter_by(id=note_id).first()))


# Passwordless sign-in -----------------------------------------------------------------

def test_sign_up_and_in_by_email_link(live_server, new_page):
    page = new_page()
    email = f"newbie{len(live_server.outbox)}@example.com"
    page.goto(f"{live_server.url}/login")
    page.fill("#email", email)
    page.click("#submit")
    expect(page).to_have_url(f"{live_server.url}/login/sent")
    expect(page.locator("h1")).to_have_text("Check your email")

    link = live_server.link_for(email)
    # Mail scanners "open" links; that must not use them up
    scanner = new_page()
    scanner.goto(link)
    expect(scanner.locator("#submit")).to_have_text("Create my notebook")

    page.goto(link)
    page.click("#submit")
    expect(page).to_have_url(f"{live_server.url}/")
    expect(page.locator(".toast")).to_contain_text("Welcome")
    page.goto(f"{live_server.url}/lounge")
    expect(page.locator("body")).to_contain_text(f"Signed in as {email}")

    # The link worked once
    page.goto(link)
    expect(page.locator(".toast")).to_contain_text("expired or was already used")


# Local-first ----------------------------------------------------------------------------

def test_write_and_stash_without_an_account(live_server, new_page):
    page = new_page()
    page.goto(live_server.url + "/")
    note_id = _stash(page, "Things to bring\n[ ] Lunch", tags="trips")
    expect(page.locator(".toast")).to_contain_text("Stashed.")
    expect(page.locator("#sheet-status")).to_contain_text("Sign in to sync")

    page.goto(f"{live_server.url}/stashes")
    expect(page.locator(".stash-card-title")).to_have_text("Things to bring")
    page.reload()  # it's in this browser's storage, not the server
    expect(page.locator(".stash-card")).to_have_count(1)
    assert _server_note(live_server, note_id) is None


def test_notes_join_the_account_and_reach_other_devices(live_server, new_page):
    username = live_server.create_user("roamer")
    laptop = new_page()
    laptop.goto(live_server.url + "/")
    note_id = _stash(laptop, "Written before signing in")

    login(laptop, live_server, username)
    assert _eventually(lambda: _server_note(live_server, note_id)) == ("Written before signing in", [], username)

    phone = new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    login(phone, live_server, username)
    phone.goto(f"{live_server.url}/stashes")
    expect(phone.locator(".stash-card-title")).to_have_text("Written before signing in")
    phone.click(".stash-card")
    expect(phone.locator("#sheet-text")).to_have_value("Written before signing in")


def test_edits_offline_then_sync(live_server, new_page):
    username = live_server.create_user()
    page = new_page()
    login(page, live_server, username)
    note_id = _stash(page, "Field trip")
    assert _eventually(lambda: _server_note(live_server, note_id))

    page.context.set_offline(True)
    text = page.locator("#sheet-text")
    text.click()
    text.press("End")
    text.type("\nBring a jacket")
    expect(page.locator("#sheet-status")).to_contain_text("Offline", timeout=8000)
    assert _server_note(live_server, note_id)[0] == "Field trip"

    page.context.set_offline(False)
    page.evaluate("window.dispatchEvent(new Event('online'))")
    assert _eventually(lambda: _server_note(live_server, note_id)[0] == "Field trip\nBring a jacket")


def test_sheet_lists_roster_and_shortcut(live_server, new_page):
    page = new_page()
    page.goto(live_server.url + "/")
    text = page.locator("#sheet-text")
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

    roster = page.locator("#roster-list li")
    expect(roster).to_have_count(2)
    roster.nth(0).locator("input").check()
    expect(text).to_have_value(re.compile(r"\[x\] Find the ball"))
    expect(page.locator("#word-count")).to_contain_text("words")

    text.press("Control+s")
    page.wait_for_url(re.compile(r"/stashes/[0-9a-f-]{36}$"))
    expect(page.locator("#sheet-text")).to_have_value(re.compile(r"^Kickball plan\n\[x\] Find the ball"))


def test_search_tags_and_toss(live_server, new_page):
    page = new_page()
    page.goto(live_server.url + "/")
    _stash(page, "Field trip\nBring lunch", tags="trips")
    _stash(page, "Science fair\nA model of the jungle gym", tags="school")
    _stash(page, "Swing schedule")

    page.goto(f"{live_server.url}/stashes")
    expect(page.locator(".stash-card")).to_have_count(3)
    page.fill("#search", "jungle")
    expect(page.locator(".stash-card")).to_have_count(1)
    expect(page.locator(".stash-card-title")).to_have_text("Science fair")
    page.fill("#search", "")
    page.click(".chip >> text=#trips")
    expect(page.locator(".stash-card")).to_have_count(1)

    page.click(".stash-card")
    expect(page.locator("#sheet-text")).to_have_value("Field trip\nBring lunch")
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.click("#toss-button")
    expect(page.locator("#sheet-text")).to_be_visible()
    page.once("dialog", lambda dialog: dialog.accept())
    page.click("#toss-button")
    expect(page.locator(".toast")).to_contain_text("Tossed it.")
    expect(page.locator(".stash-card")).to_have_count(2)


# Folded notes ---------------------------------------------------------------------------

def test_fold_pass_and_unfold_once(live_server, new_page):
    from models import FoldedNote
    username = live_server.create_user("folder")
    sender = new_page()
    login(sender, live_server, username)
    _stash(sender, "Meet at the monkey bars\nBring the kickball")
    sender.click("#fold-button")
    expect(sender.locator("#fold-panel")).to_be_visible()
    link = sender.locator("#fold-url").input_value()
    qr = sender.locator("#fold-qr")
    expect(qr).to_be_visible()
    assert qr.get_attribute("src").startswith("data:image/gif;base64,")
    assert re.search(r"/f/[A-Za-z0-9_-]{16,32}#[A-Za-z0-9_-]{40,}$", link)

    # The server holds only ciphertext
    stored = live_server.query(lambda: [n.ciphertext for n in FoldedNote.query.all()])
    assert stored and all("monkey" not in c for c in stored)

    friend = new_page()
    friend.goto(link)
    expect(friend.locator("#unfold-closed h1")).to_have_text("Someone passed you a note")
    friend.click("#unfold")
    expect(friend.locator("#unfold-text")).to_have_text("Meet at the monkey bars\nBring the kickball")
    assert "#" not in friend.url  # key dropped from the address bar
    friend.click("#unfold-keep")
    friend.wait_for_url(re.compile(r"/stashes/[0-9a-f-]{36}$"))
    expect(friend.locator("#sheet-text")).to_have_value("Meet at the monkey bars\nBring the kickball")

    # Opened once: gone for everyone else, and from the server
    late = new_page()
    late.goto(link)
    expect(late.locator("main h1")).to_have_text("Already unfolded")
    assert live_server.query(lambda: FoldedNote.query.count()) == 0


# Backups, sign-out, relay ---------------------------------------------------------------

def test_backup_then_restore(live_server, new_page, tmp_path):
    page = new_page()
    page.goto(live_server.url + "/")
    _stash(page, "Keep me\n[x] step one", tags="safe")

    page.goto(f"{live_server.url}/lounge")
    with page.expect_download() as download_info:
        page.click("#backup-button")
    backup = tmp_path / "backup.json"
    download_info.value.save_as(backup)
    data = json.loads(backup.read_text(encoding="utf-8"))
    assert [(s["title"], s["tags"], s["checklist"]) for s in data["stashes"]] == \
        [("Keep me", ["safe"], [{"text": "step one", "done": True}])]

    page.goto(f"{live_server.url}/stashes")
    page.click(".stash-card")
    page.once("dialog", lambda dialog: dialog.accept())
    page.click("#toss-button")
    expect(page.locator(".stash-card")).to_have_count(0)

    page.goto(f"{live_server.url}/lounge")
    page.set_input_files("#file-input", str(backup))
    page.get_by_role("button", name="Restore", exact=True).click()
    expect(page.locator(".toast", has_text="Restored 1 note.")).to_be_visible()
    page.goto(f"{live_server.url}/stashes")
    expect(page.locator(".stash-card-title")).to_have_text("Keep me")


def test_signing_out_clears_this_device(live_server, new_page):
    username = live_server.create_user()
    page = new_page()
    login(page, live_server, username)
    note_id = _stash(page, "Private plans")
    assert _eventually(lambda: _server_note(live_server, note_id))

    page.goto(f"{live_server.url}/lounge")
    page.get_by_role("button", name="Sign out", exact=True).click()
    expect(page.locator(".toast")).to_contain_text("Logged out")
    page.goto(f"{live_server.url}/stashes")
    expect(page.locator("#stash-empty")).to_be_visible()
    assert _server_note(live_server, note_id)[0] == "Private plans"  # still safe in the account


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

    guest = new_page()
    guest.goto(f"{live_server.url}/pass")
    guest.fill("#relay-code", code.lower())
    guest.click("button:has-text('Join')")
    expect(guest.locator(".relay-prompt")).to_have_text("Once upon a recess")
    guest.fill("#relay-author", "Visitor")
    guest.fill("#relay-body", "a dragon joined the game")
    guest.click("text=Pass it on")
    expect(guest.locator(".relay-line")).to_contain_text("a dragon joined the game")

    expect(guest.locator("text=Close relay")).to_have_count(0)
    owner.reload()
    expect(owner.locator(".relay-author")).to_have_text("Visitor")
    owner.once("dialog", lambda dialog: dialog.accept())
    owner.click("text=Close relay")
    expect(owner.locator(".toast")).to_contain_text("Relay closed")
    guest.reload()
    expect(guest.locator("#relay-body")).to_have_count(0)
    expect(guest.locator("text=This relay is closed.")).to_be_visible()
