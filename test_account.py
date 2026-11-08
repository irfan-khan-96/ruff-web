"""
Account tests: deleting an account, passkey endpoints, and which pages the
service worker may keep for offline use. The full passkey ceremony runs in a
real browser in test_e2e_flows.py.
"""

import pytest

from app import create_app
from conftest import sign_in
from models import db, FoldedNote, Passkey, RelayEntry, RelaySession, Stash, StashTombstone, User
from utils import utcnow
from datetime import timedelta

JSON = {"Accept": "application/json"}


@pytest.fixture
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def make_user(name):
    user = User(username=name, email=f"{name}@example.com", email_verified=True)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def alice(app):
    return make_user("alice")


@pytest.fixture
def client(app, alice):
    return sign_in(app.test_client(), alice)


# Deleting an account ---------------------------------------------------------------

def fill_account(user):
    note = Stash(body="secret plan", user_id=user.id)
    note.add_tag("recess")
    relay = RelaySession(code=f"R{user.id:05d}", owner_id=user.id, title="Story")
    db.session.add_all([
        note, relay,
        StashTombstone(stash_id="00000000-0000-4000-8000-%012d" % user.id, user_id=user.id),
        FoldedNote(id=f"fold{user.id}", sender_id=user.id, ciphertext="c", iv="i",
                   expires_at=utcnow() + timedelta(days=1)),
        Passkey(user_id=user.id, credential_id=f"cred{user.id}", public_key=b"k"),
    ])
    db.session.flush()
    db.session.add(RelayEntry(session_id=relay.id, author_name=user.username, body="Once", position=1))
    db.session.commit()


def counts(user_id):
    return [
        Stash.query.filter_by(user_id=user_id).count(),
        StashTombstone.query.filter_by(user_id=user_id).count(),
        FoldedNote.query.filter_by(sender_id=user_id).count(),
        RelaySession.query.filter_by(owner_id=user_id).count(),
        Passkey.query.filter_by(user_id=user_id).count(),
    ]


def test_delete_account_needs_the_email_typed(app, alice, client):
    response = client.post("/account/delete", data={"confirm_email": "wrong@example.com"})
    assert response.status_code == 302 and response.headers["Location"].endswith("/lounge#delete")
    assert db.session.get(User, alice.id) is not None


def test_delete_account_removes_everything_it_owns(app, alice, client):
    bob = make_user("bob")
    fill_account(alice)
    fill_account(bob)
    alice_id = alice.id

    response = client.post("/account/delete", data={"confirm_email": "Alice@Example.com"})
    assert response.headers["Location"] == "/login"
    db.session.expire_all()
    assert db.session.get(User, alice_id) is None
    assert counts(alice_id) == [0, 0, 0, 0, 0]
    assert RelayEntry.query.count() == 1  # only bob's relay is left
    assert counts(bob.id) == [1, 1, 1, 1, 1]
    assert db.session.execute(db.text("SELECT count(*) FROM stash_tags")).scalar() == 1
    # Signed out
    assert client.get("/api/sync", headers=JSON).status_code in (401, 405)
    assert client.post("/api/sync", json={}, headers=JSON).status_code == 401


def test_delete_account_needs_sign_in(app):
    response = app.test_client().post("/account/delete", data={"confirm_email": "x@example.com"})
    assert response.status_code == 302 and response.headers["Location"] == "/login"


# Passkeys --------------------------------------------------------------------------

def test_adding_a_passkey_needs_sign_in(app):
    assert app.test_client().post("/passkeys/options", headers=JSON).status_code == 401
    assert app.test_client().post("/passkeys", json={}, headers=JSON).status_code == 401


def test_registration_options_ask_for_a_discoverable_passkey(app, alice, client):
    db.session.add(Passkey(user_id=alice.id, credential_id="AAAA", public_key=b"k"))
    db.session.commit()
    options = client.post("/passkeys/options", headers=JSON).get_json()
    assert options["rp"] == {"name": "Ruff", "id": "localhost"}  # this host by default
    assert options["user"]["name"] == "alice@example.com"
    assert options["authenticatorSelection"]["residentKey"] == "required"
    assert [c["id"] for c in options["excludeCredentials"]] == ["AAAA"]
    assert len(options["challenge"]) >= 43


def test_configured_relying_party_wins_over_host(app, client):
    app.config["WEBAUTHN_RP_ID"] = "ruff.example"
    options = client.post("/passkeys/options", headers=JSON).get_json()
    assert options["rp"]["id"] == "ruff.example"


def test_junk_registration_is_refused(app, client):
    assert client.post("/passkeys", json={"id": "x"}, headers=JSON).status_code == 400  # no challenge yet
    client.post("/passkeys/options", headers=JSON)
    response = client.post("/passkeys", json={"id": "x", "rawId": "x", "response": {}}, headers=JSON)
    assert response.status_code == 400 and "error" in response.get_json()
    assert Passkey.query.count() == 0


def test_sign_in_options_name_no_accounts(app):
    client = app.test_client()
    options = client.post("/login/passkey/options", headers=JSON).get_json()
    assert options["rpId"] == "localhost" and options.get("allowCredentials", []) == []


def test_unknown_passkey_cannot_sign_in(app, alice):
    client = app.test_client()
    client.post("/login/passkey/options", headers=JSON)
    response = client.post("/login/passkey", json={"id": "nope"}, headers=JSON)
    assert response.status_code == 400
    with client.session_transaction() as sess:
        assert "user_id" not in sess and "passkey_challenge" not in sess


def test_challenges_are_single_use_and_purpose_bound(app, alice):
    db.session.add(Passkey(user_id=alice.id, credential_id="cred", public_key=b"k"))
    db.session.commit()
    client = sign_in(app.test_client(), alice)
    client.post("/passkeys/options", headers=JSON)  # a registration challenge...
    # ...can't be used to sign in
    assert client.post("/login/passkey", json={"id": "cred"}, headers=JSON).status_code == 400


def test_cannot_remove_someone_elses_passkey(app, alice):
    bob = make_user("bob")
    key = Passkey(user_id=bob.id, credential_id="bobs", public_key=b"k")
    db.session.add(key)
    db.session.commit()
    client = sign_in(app.test_client(), alice)
    assert client.post(f"/passkeys/{key.id}/delete").status_code == 404
    assert db.session.get(Passkey, key.id) is not None


def test_removing_a_passkey(app, alice, client):
    key = Passkey(user_id=alice.id, credential_id="mine", public_key=b"k")
    db.session.add(key)
    db.session.commit()
    assert b"Added" in client.get("/lounge").data
    assert client.post(f"/passkeys/{key.id}/delete").headers["Location"] == "/lounge"
    assert Passkey.query.count() == 0


# Offline shells --------------------------------------------------------------------

def test_shell_pages_may_be_kept_offline(app, client):
    for path in ("/", "/stashes", "/pass", "/lounge"):
        assert client.get(path).headers.get("X-Offline-Shell") == "1", path
    for path in ("/login", "/relay", "/stashes/00000000-0000-4000-8000-000000000000"):
        assert "X-Offline-Shell" not in client.get(path).headers, path


def test_pages_with_one_off_messages_are_not_kept(app, client):
    with client.session_transaction() as sess:
        sess["_flashes"] = [("success", "Welcome back.")]
    assert "X-Offline-Shell" not in client.get("/").headers
    assert client.get("/").headers.get("X-Offline-Shell") == "1"


def test_service_worker_is_never_long_cached(app):
    response = app.test_client().get("/sw.js")
    assert response.status_code == 200 and b"X-Offline-Shell" in response.data
    assert "max-age=0" in response.headers.get("Cache-Control", "") or "no-cache" in response.headers.get("Cache-Control", "")
