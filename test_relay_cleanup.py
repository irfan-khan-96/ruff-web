"""
Recess Relay retention: expired relays disappear and get purged with their entries.
"""

from datetime import timedelta

import pytest

from app import create_app
from models import db, User, RelaySession, RelayEntry
from utils import utcnow


@pytest.fixture
def app():
    app = create_app("testing")
    app.config["RELAY_RETENTION_DAYS"] = 30
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def owner(app):
    user = User(username="owner", email="owner@example.com", email_verified=True)
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    return user


def make_relay(owner, code, age_days, entries=2):
    relay = RelaySession(code=code, owner_id=owner.id, title=code,
                         created_at=utcnow() - timedelta(days=age_days))
    db.session.add(relay)
    db.session.flush()
    for position in range(1, entries + 1):
        db.session.add(RelayEntry(session_id=relay.id, author_name="a", body="line", position=position))
    db.session.commit()
    return relay


def test_purge_deletes_only_expired_relays_and_their_entries(app, owner):
    make_relay(owner, "OLD001", age_days=31)
    make_relay(owner, "OLD002", age_days=90, entries=0)
    fresh = make_relay(owner, "NEW001", age_days=1)

    assert RelaySession.purge_expired(30) == 2

    assert [r.code for r in RelaySession.query.all()] == ["NEW001"]
    assert {e.session_id for e in RelayEntry.query.all()} == {fresh.id}


def test_expired_relay_is_not_found_before_purge(app, owner):
    make_relay(owner, "OLD001", age_days=31)
    make_relay(owner, "NEW001", age_days=1)
    client = app.test_client()

    assert client.get("/relay/OLD001").status_code == 404
    assert client.post("/relay/OLD001/add", data={"body": "late"}).status_code == 404
    assert client.get("/relay/NEW001").status_code == 200


def test_starting_a_relay_purges_expired_ones(app, owner):
    make_relay(owner, "OLD001", age_days=31)
    client = app.test_client()
    client.post("/login", data={"username": "owner", "password": "password123"})

    response = client.post("/relay", data={"action": "start", "title": "Fresh"})

    assert response.status_code == 302
    assert [r.title for r in RelaySession.query.all()] == ["Fresh"]
    assert RelayEntry.query.count() == 0


def test_purge_relays_cli_command(app, owner):
    make_relay(owner, "OLD001", age_days=31)
    make_relay(owner, "NEW001", age_days=1)

    result = app.test_cli_runner().invoke(args=["purge-relays"])

    assert "Deleted 1 relay session(s) older than 30 days." in result.output
    assert [r.code for r in RelaySession.query.all()] == ["NEW001"]
