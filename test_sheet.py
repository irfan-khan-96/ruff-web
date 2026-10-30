"""
The sheet: one plain-text note per stash (first line = title, "[ ] task"
lines = Recess Roster), stashing and listing, and backups.
"""

import io
import json
from datetime import timedelta

import pytest

from conftest import sign_in

from app import create_app
from models import db, Stash, Tag, User
from utils import compose_sheet, roster_items, sheet_preview, sheet_title, time_ago, utcnow

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
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def client(app, user):
    return sign_in(app.test_client(), user)


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

def test_anyone_can_write_and_browse_their_device(app):
    """Local-first: the sheet and the stash list work without an account."""
    client = app.test_client()
    for path in ["/", "/stashes", "/stashes/0e9f6a4c-1d2b-4c3d-8e4f-5a6b7c8d9e0f", "/lounge", "/pass"]:
        assert client.get(path).status_code == 200, path
    assert client.get("/stashes/not-a-uuid").status_code == 404


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
    db.session.add(other)
    db.session.flush()
    theirs = Stash(body="theirs", user_id=other.id)
    db.session.add(theirs)
    db.session.commit()
    assert stash(client, "mine now", stash_id=theirs.id).status_code == 404
    assert db.session.get(Stash, theirs.id).body == "theirs"


# Sync ------------------------------------------------------------------------------

import time
import uuid

NOW = lambda: int(time.time() * 1000)  # noqa: E731


def sync(client, changes=(), cursor=None):
    response = client.post("/api/sync", json={"cursor": cursor, "changes": list(changes)}, headers=JSON)
    assert response.status_code == 200, response.data
    return response.get_json()


def test_sync_uploads_then_returns_changes_since_cursor(client):
    note = {"id": str(uuid.uuid4()), "text": "Plan\n[ ] ball", "tags": ["Recess"], "updated_at": NOW()}
    first = sync(client, [note])
    assert first["accepted"] == [note["id"]] and first["rejected"] == []
    assert [(s["text"], s["tags"]) for s in first["stashes"]] == [("Plan\n[ ] ball", ["recess"])]
    stored = db.session.get(Stash, note["id"])
    assert (stored.title, stored.get_checklist()) == ("Plan", [{"text": "ball", "done": False}])
    # Nothing new since the cursor (apart from the overlap window, which repeats harmlessly)
    again = sync(client, cursor=first["cursor"])
    assert {s["id"] for s in again["stashes"]} <= {note["id"]} and again["deleted"] == []


def test_newer_edit_wins(client):
    note_id = str(uuid.uuid4())
    sync(client, [{"id": note_id, "text": "v1", "tags": [], "updated_at": NOW()}])
    sync(client, [{"id": note_id, "text": "older", "tags": [], "updated_at": NOW() - 60_000}])
    assert db.session.get(Stash, note_id).body == "v1"
    sync(client, [{"id": note_id, "text": "v2", "tags": [], "updated_at": NOW() + 10}])
    db.session.expire_all()
    assert db.session.get(Stash, note_id).body == "v2"


def test_deletions_reach_other_devices(app, client, user):
    other_device = sign_in(app.test_client(), user)
    note_id = str(uuid.uuid4())
    sync(client, [{"id": note_id, "text": "toss me", "tags": [], "updated_at": NOW()}])
    cursor = sync(other_device)["cursor"]
    sync(client, [{"id": note_id, "deleted": True, "updated_at": NOW() + 10}])
    assert sync(other_device, cursor=cursor)["deleted"] == [note_id]
    assert db.session.get(Stash, note_id) is None


def test_sync_validates_every_change(client):
    reply = sync(client, [
        {"id": "nope", "text": "x", "updated_at": NOW()},
        {"id": str(uuid.uuid4()), "text": "   ", "updated_at": NOW()},
        {"id": str(uuid.uuid4()), "text": "x" * 50001, "updated_at": NOW()},
        {"id": str(uuid.uuid4()), "text": "ok", "updated_at": "yesterday"},
    ])
    assert [r["reason"].split(".")[0] for r in reply["rejected"]] == [
        "bad id", "Write something first", "That's too long", "bad timestamp"]
    assert client.post("/api/sync", json={"changes": [{}] * 501}, headers=JSON).status_code == 400


def test_sync_needs_an_account(app):
    assert app.test_client().post("/api/sync", json={}, headers=JSON).status_code == 401


# Folded notes ---------------------------------------------------------------------------

def test_fold_stores_ciphertext_and_opens_once(app, client):
    from models import FoldedNote
    reply = client.post("/fold", json={"ciphertext": "c2VjcmV0", "iv": "aXYxMjM0NTY3ODkw"}, headers=JSON)
    assert reply.status_code == 201
    note_id = reply.get_json()["url"].rsplit("/", 1)[1]
    assert db.session.get(FoldedNote, note_id).ciphertext == "c2VjcmV0"

    reader = app.test_client()
    assert b"Unfold it" in reader.get(f"/f/{note_id}").data  # looking doesn't open it
    assert reader.post(f"/f/{note_id}/open").get_json() == {"ciphertext": "c2VjcmV0", "iv": "aXYxMjM0NTY3ODkw"}
    assert reader.post(f"/f/{note_id}/open").status_code == 404
    assert b"Already unfolded" in reader.get(f"/f/{note_id}").data
    assert db.session.get(FoldedNote, note_id) is None


def test_expired_folded_notes_dont_open(app, client):
    from datetime import timedelta
    from models import FoldedNote
    note_id = client.post("/fold", json={"ciphertext": "eA", "iv": "eA"}, headers=JSON).get_json()["url"].rsplit("/", 1)[1]
    db.session.get(FoldedNote, note_id).expires_at = utcnow() - timedelta(seconds=1)
    db.session.commit()
    assert app.test_client().post(f"/f/{note_id}/open").status_code == 404
    assert app.test_cli_runner().invoke(args=["purge-expired"]).output.strip().endswith("1 expired folded note(s).")


@pytest.mark.parametrize("payload", [
    {"ciphertext": "not base64!", "iv": "eA"},
    {"ciphertext": "eA", "iv": "x" * 40},
    {"ciphertext": "a" * 120_001, "iv": "eA"},
    {},
])
def test_fold_rejects_junk(client, payload):
    assert client.post("/fold", json=payload, headers=JSON).status_code == 400


def test_folding_needs_an_account(app):
    assert app.test_client().post("/fold", json={"ciphertext": "eA", "iv": "eA"}, headers=JSON).status_code == 401


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
