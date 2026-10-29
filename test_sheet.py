"""
The sheet: one plain-text note per stash (first line = title, "[ ] task"
lines = Recess Roster), stashing and listing, and backups.
"""

import io
import json
from datetime import timedelta

import pytest

from app import create_app
from models import db, Stash, Tag, User
from utils import compose_sheet, roster_items, sheet_preview, sheet_title, time_ago, utcnow

PASSWORD = "correct-horse-battery"
JSON = {"Accept": "application/json"}


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
    user = User(username="kid", email="kid@example.com", email_verified=True)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def client(app, user):
    client = app.test_client()
    client.post("/login", data={"username": "kid", "password": PASSWORD})
    return client


def stash(client, text, tags="", stash_id=""):
    return client.post("/stash", json={"text": text, "tags": tags, "stash_id": stash_id}, headers=JSON)


# Parsing the sheet -----------------------------------------------------------

def test_title_is_first_line():
    assert sheet_title("\n\n  Kickball plan  \nmore") == "Kickball plan"
    assert sheet_title("[ ] buy milk\nnext") == "buy milk"
    assert sheet_title("# Heading\ntext") == "Heading"
    assert sheet_title("   \n") is None


def test_roster_items_from_task_lines():
    text = "Plan\n[ ] find ball\n- [x] ask for field\n[X] done too\n[ ]   \nnot a task [ ]"
    assert roster_items(text) == [
        {"text": "find ball", "done": False},
        {"text": "ask for field", "done": True},
        {"text": "done too", "done": True},
    ]


def test_preview_skips_title_and_tasks():
    assert sheet_preview("Title\nfirst words\n[ ] task\nmore words") == "first words more words"
    assert sheet_preview("Only a title") == "Only a title"


def test_compose_sheet_from_old_fields():
    assert compose_sheet("Bring lunch", "Field trip", [{"text": "slip", "done": True}]) == \
        "Field trip\n\nBring lunch\n\n[x] slip"
    # The title isn't repeated when the body already starts with it
    assert compose_sheet("Field trip\nBring lunch", "Field trip") == "Field trip\nBring lunch"


def test_time_ago():
    now = utcnow()
    assert time_ago(now, now) == "just now"
    assert time_ago(now - timedelta(minutes=2), now) == "2 minutes ago"
    assert time_ago(now - timedelta(hours=1), now) == "1 hour ago"
    assert time_ago(now - timedelta(days=3), now) == "3 days ago"


def test_stash_fields_follow_the_text(app, user):
    item = Stash(body="Plan\nwords\n[x] one\n[ ] two", user_id=user.id)
    assert (item.title, item.preview) == ("Plan", "words")
    assert item.get_checklist() == [{"text": "one", "done": True}, {"text": "two", "done": False}]
    item.set_text("New title")
    assert (item.title, item.get_checklist()) == ("New title", [])


# Stashing --------------------------------------------------------------------

def test_anyone_can_open_the_sheet(app):
    response = app.test_client().get("/")
    assert response.status_code == 200
    assert b"Sign up to stash" in response.data


def test_stashing_needs_an_account(app):
    response = app.test_client().post("/stash", json={"text": "hi"}, headers=JSON)
    assert response.status_code == 401
    assert response.get_json()["error"] == "login_required"


def test_create_then_update(client, user):
    created = stash(client, "Kickball\n[ ] ball", tags="Recess, #team, recess")
    assert created.status_code == 200
    data = created.get_json()
    assert data["title"] == "Kickball" and data["tags"] == ["recess", "team"]

    updated = stash(client, "Kickball v2", tags="team", stash_id=data["id"])
    assert updated.get_json()["tags"] == ["team"]
    item = db.session.get(Stash, data["id"])
    assert (item.title, item.checklist) == ("Kickball v2", None)
    assert updated.get_json()["version"] == item.updated_at.isoformat()


def test_stash_without_javascript(client):
    response = client.post("/stash", data={"text": "Plain form post", "tags": ""})
    assert response.status_code == 302
    assert "/stashes/" in response.headers["Location"]


@pytest.mark.parametrize("payload, message", [
    ({"text": "   "}, "Write something first."),
    ({"text": "x" * 50001}, "That's too long"),
    ({"text": "ok", "tags": ",".join(f"t{n}" for n in range(21))}, "Up to 20 tags"),
    ({"text": "ok", "tags": "x" * 51}, "Up to 20 tags"),
])
def test_stash_validation(client, payload, message):
    response = client.post("/stash", json=payload, headers=JSON)
    assert response.status_code == 400
    assert response.get_json()["error"].startswith(message)


def test_cannot_update_someone_elses_stash(app, client):
    other = User(username="other", email="other@example.com", email_verified=True)
    other.set_password(PASSWORD)
    db.session.add(other)
    db.session.flush()
    theirs = Stash(body="theirs", user_id=other.id)
    db.session.add(theirs)
    db.session.commit()
    assert stash(client, "mine now", stash_id=theirs.id).status_code == 404
    assert db.session.get(Stash, theirs.id).body == "theirs"


def test_open_and_toss(client):
    item_id = stash(client, "Toss me").get_json()["id"]
    page = client.get(f"/stashes/{item_id}")
    assert page.status_code == 200 and b"Toss me" in page.data
    assert client.post(f"/stashes/{item_id}/delete").status_code == 302
    assert client.get(f"/stashes/{item_id}").status_code == 404


# The stash list ----------------------------------------------------------------

def test_list_search_tags_and_pages(client):
    for n in range(32):
        stash(client, f"note {n}", tags="even" if n % 2 == 0 else "")
    stash(client, "Kickball plan", tags="recess")

    first = client.get("/stashes").get_data(as_text=True)
    assert first.count('class="stash-card"') == 30 and "Load more" in first
    second = client.get("/stashes?page=2").get_data(as_text=True)
    assert second.count('class="stash-card"') == 3 and "Load more" not in second

    assert client.get("/stashes?q=kickball").get_data(as_text=True).count('class="stash-card"') == 1
    assert client.get("/stashes?tag=even").get_data(as_text=True).count('class="stash-card"') == 16


def test_empty_list_invites_writing(client):
    assert b"Your stash is empty." in client.get("/stashes").data


# Backups -----------------------------------------------------------------------

def test_export_then_restore(client, user):
    item_id = stash(client, "Keep me\n[x] step one", tags="safe").get_json()["id"]
    backup = client.get("/export").get_data(as_text=True)
    data = json.loads(backup)
    assert data["version"] == "2.0"
    assert data["stashes"][0]["checklist"] == [{"text": "step one", "done": True}]

    client.post(f"/stashes/{item_id}/delete")
    response = client.post("/import", data={"file": (io.BytesIO(backup.encode()), "backup.json")},
                           content_type="multipart/form-data", follow_redirects=True)
    assert "Restored 1 stash." in response.get_data(as_text=True)
    restored = db.session.get(Stash, item_id)
    assert restored.body == "Keep me\n[x] step one" and [t.name for t in restored.tags] == ["safe"]


def test_restore_old_backup_with_collections(client, user):
    old = {
        "version": "1.0",
        "collections": [{"id": 7, "name": "School Stuff"}],
        "stashes": [{"id": "old-1", "title": "Field trip", "body": "Bring lunch",
                     "checklist": [{"text": "slip", "done": True}], "collection_id": 7, "tags": ["trips"]}],
    }
    client.post("/import", data={"file": (io.BytesIO(json.dumps(old).encode()), "old.json")},
                content_type="multipart/form-data")
    item = db.session.get(Stash, "old-1")
    assert item.body == "Field trip\n\nBring lunch\n\n[x] slip"
    assert sorted(t.name for t in item.tags) == ["school stuff", "trips"]


def test_download_single_stash_as_text(client):
    item_id = stash(client, "Trip\n[ ] lunch", tags="b, a").get_json()["id"]
    response = client.get(f"/export/stash/{item_id}")
    assert response.get_data(as_text=True) == "Trip\n[ ] lunch\n\nTags: #a, #b\n"
    assert "stash-Trip.txt" in response.headers["Content-Disposition"]
