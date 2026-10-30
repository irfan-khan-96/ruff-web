"""
Route handlers for the Ruff application.
"""

import hmac
import logging
import os
import json
import re
import secrets
import string
from datetime import datetime, timedelta, timezone

from utils import utcnow
from functools import wraps
from flask import Blueprint, render_template, session, redirect, url_for, flash, current_app, request, g, send_file, send_from_directory, abort
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import delete as sa_delete, func, text
from werkzeug.exceptions import HTTPException
from io import BytesIO

from forms import EmailForm, NameForm
from models import db, FoldedNote, RelayEntry, RelaySession, Stash, StashTombstone, Tag, User
from export_import import (
    export_to_json,
    export_stash_to_text,
    import_from_json,
    MAX_TITLE_LENGTH,
    MAX_TAG_LENGTH,
)
from auth_utils import (
    load_session_user,
    login_link_token,
    read_link_token,
    send_email,
    signup_link_token,
    start_session,
)

logger = logging.getLogger(__name__)
# Security events (failed logins, resets, rate limits) for monitoring/alerting
security_log = logging.getLogger("ruff.security")

bp = Blueprint("main", __name__)
csrf = CSRFProtect()
_default_limits = [
    limit.strip()
    for limit in os.getenv("RATELIMIT_DEFAULT", "200 per day;50 per hour").split(";")
    if limit.strip()
]
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=_default_limits,
    storage_uri=os.getenv("RATELIMIT_STORAGE_URL", "memory://"),
)


# Health and readiness probes -------------------------------------------------
@bp.route("/healthz", methods=["GET"])
def healthz():
    """Lightweight health check for load balancers."""
    return {"status": "ok"}, 200


@bp.route("/readyz", methods=["GET"])
def readyz():
    """Readiness check: the database is reachable and migrated."""
    try:
        # Querying a real table fails until migrations have created the schema
        db.session.execute(text("SELECT 1 FROM users LIMIT 1"))
        return {"status": "ok"}, 200
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        logger.error(f"Readiness check failed: {e}")
        return {"status": "error"}, 503


@bp.route("/sw.js")
def service_worker():
    """Serve the service worker at the app root (never long-cached, so updates land)."""
    return send_from_directory(current_app.static_folder, "sw.js", max_age=0)


def login_required(f):
    """Decorator to require login for a route."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if g.get("user") is None:
            if wants_json():
                return {"error": "login_required", "login_url": url_for("main.login")}, 401
            flash("Log in first, then you're good to go.", "info")
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return decorated_function


@bp.before_request
def load_logged_in_user():
    """Load the logged-in user from session."""
    g.user = load_session_user(session)


def purge_expired_relays() -> None:
    """Opportunistic cleanup when relays are created; never blocks the request."""
    try:
        RelaySession.purge_expired(current_app.config["RELAY_RETENTION_DAYS"])
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        logger.error(f"Relay cleanup failed: {e}")


def get_active_relay_or_404(code: str) -> RelaySession:
    """Look up a relay by code, treating expired ones as gone."""
    relay = RelaySession.query.filter_by(code=code.upper()).first_or_404()
    if relay.is_expired(current_app.config["RELAY_RETENTION_DAYS"]):
        abort(404)
    return relay


def safe_filename_part(text: str, max_length: int = 30) -> str:
    """Filename-safe slug of user text (no line breaks, quotes or path characters)."""
    slug = "".join(ch if ch.isalnum() or ch in " -_" else " " for ch in text)
    slug = "-".join(slug.split())[:max_length].strip("-")
    return slug or "untitled"


def generate_relay_code(length: int = 6) -> str:
    """Generate a short uppercase relay code."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ============================================================================
# Passwordless sign-in: email links
# ============================================================================

LOGIN_LINK_MAX_AGE = 15 * 60  # seconds


def _login_email_key() -> str:
    """Rate-limit key for sign-in links sent to one address, from any IP."""
    return "login-email:" + (request.form.get("email") or "").strip().lower()


def unique_username(email: str) -> str:
    """A starting name from the email's local part (changeable in the Lounge)."""
    base = re.sub(r"[^a-z0-9_.-]", "", email.split("@", 1)[0].lower())[:24]
    base = base if len(base) >= 3 else f"{base}pal"
    name, n = base, 1
    while User.query.filter_by(username=name).first():
        n += 1
        name = f"{base}{n}"
    return name


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])  # per IP
@limiter.limit("10 per hour", key_func=_login_email_key, methods=["POST"])  # per address
def login():
    """Sign in or sign up: we email a link either way (no passwords)."""
    if g.user is not None:
        return redirect(url_for("main.index"))

    form = EmailForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter(func.lower(User.email) == email).first()
        app_name = current_app.config["APP_NAME"]
        if user:
            token = login_link_token(user)
            db.session.commit()
            subject, intro = f"Your {app_name} sign-in link", "Tap to sign in"
        else:
            token = signup_link_token(email)
            subject, intro = f"Your {app_name} notebook is ready", "Tap to start your notebook"
        link = url_for("main.auth_link", token=token, _external=True)
        send_email(email, subject,
                   f"{intro}: {link}\n\nThe link works once, within 15 minutes. "
                   "If you didn't ask for it, you can ignore this email.")
        # Same answer whether or not the address has an account (no enumeration)
        security_log.info("Sign-in link requested from %s (account exists: %s)", request.remote_addr, bool(user))
        return redirect(url_for("main.check_email"))

    return render_template("login.html", form=form)


@bp.route("/login/sent")
def check_email():
    return render_template("check_email.html")


def _link_user(data):
    """The account a link signs into, or None if the link is spent/invalid."""
    if data["purpose"] == "login":
        user = db.session.get(User, data.get("uid"))
        if user and user.login_nonce and hmac.compare_digest(user.login_nonce, str(data.get("nonce", ""))):
            return user
        return None
    # signup: valid until the account exists
    email = str(data.get("email", "")).strip().lower()
    if not email or User.query.filter(func.lower(User.email) == email).first():
        return None
    return email


@bp.route("/auth/<token>", methods=["GET", "POST"])
@limiter.limit("30 per hour", methods=["POST"])
def auth_link(token):
    """
    Open a sign-in link. GET only shows a button: email security scanners open
    links automatically, and would otherwise use up the single-use link.
    """
    data, error = read_link_token(token, LOGIN_LINK_MAX_AGE)
    target = _link_user(data) if data else None
    if target is None:
        security_log.warning("Unusable sign-in link (%s) from %s", error or "used", request.remote_addr)
        flash("That link expired or was already used. Get a fresh one.", "warning")
        return redirect(url_for("main.login"))

    if request.method == "GET":
        new = isinstance(target, str)
        return render_template("auth_confirm.html", email=target if new else target.email, new=new)

    if isinstance(target, str):
        user = User(username=unique_username(target), email=target)
        db.session.add(user)
        welcome = "Your notebook's ready. Welcome!"
    else:
        user = target
        user.login_nonce = None  # spent
        welcome = f"Welcome back, {user.username}."
    user.email_verified = True
    user.email_verified_at = user.email_verified_at or utcnow()
    db.session.commit()
    start_session(session, user)
    security_log.info("Signed in user_id=%s from %s", user.id, request.remote_addr)
    flash(welcome, "success")
    return redirect(url_for("main.index"))


@bp.route("/signup")
@bp.route("/verify/resend")
@bp.route("/password/forgot")
@bp.route("/verify/<token>")
@bp.route("/password/reset/<token>")
def legacy_auth(token=None):
    """Old password, verification and reset links: sign-in is by email link now."""
    return redirect(url_for("main.login"))


@bp.route("/logout", methods=["POST"])
def logout():
    if g.user is not None:
        logger.info(f"User {g.user.username} logged out")
    session.clear()
    flash("Logged out. See you at recess.", "info")
    return redirect(url_for("main.login"))


@bp.route("/logout/everywhere", methods=["POST"])
@login_required
def logout_everywhere():
    """End every session of this account, on every device."""
    g.user.session_epoch = (g.user.session_epoch or 0) + 1
    g.user.login_nonce = None
    db.session.commit()
    security_log.info("Signed out everywhere: user_id=%s from %s", g.user.id, request.remote_addr)
    session.clear()
    flash("Signed out on every device.", "info")
    return redirect(url_for("main.login"))


# ============================================================================
# The sheet (local-first)
# Notes live in the browser (IndexedDB) and work offline and without an
# account. Signed-in devices sync through /api/sync; these pages are shells
# that the browser fills from its local store.
# ============================================================================

MAX_TAGS = 20
MAX_SYNC_CHANGES = 500
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def wants_json() -> bool:
    """True for fetch() calls (JSON in or out)."""
    return request.accept_mimetypes.best == "application/json" or request.is_json


def parse_tags(raw) -> list:
    """Comma-separated (or list) tag input -> clean, unique, lowercase names."""
    names = raw if isinstance(raw, list) else str(raw or "").split(",")
    clean = []
    for name in names:
        name = str(name).strip().lstrip("#").strip().lower()
        if name and name not in clean:
            clean.append(name)
    return clean


def note_error(text: str, tags: list):
    """Why a note can't be saved, or None."""
    if not text.strip():
        return "Write something first."
    if len(text) > current_app.config["MAX_STASH_LENGTH"]:
        return f"That's too long. Keep it under {current_app.config['MAX_STASH_LENGTH']:,} characters."
    if len(tags) > MAX_TAGS or any(len(name) > MAX_TAG_LENGTH for name in tags):
        return f"Up to {MAX_TAGS} tags, {MAX_TAG_LENGTH} characters each."
    return None


def toss(stash) -> None:
    """Delete a stash and leave a tombstone so other devices drop it too."""
    db.session.merge(StashTombstone(stash_id=stash.id, user_id=stash.user_id, deleted_at=utcnow()))
    db.session.delete(stash)


@bp.route("/")
def index():
    """A fresh sheet. Anyone can write and stash; signing in adds sync."""
    return render_template("sheet.html", stash_id=None)


@bp.route("/stashes/<stash_id>")
def view_stash(stash_id):
    """A stash, opened in the sheet (loaded from this device's store)."""
    if not UUID_RE.match(stash_id):
        abort(404)
    return render_template("sheet.html", stash_id=stash_id)


@bp.route("/stashes")
def view_stashes():
    """Everything stashed on this device (and synced from others)."""
    return render_template("stashes.html")


@bp.route("/stash", methods=["POST"])
@login_required
def stash():
    """Server-side create/update of one stash (JSON API; the app itself syncs)."""
    data = request.get_json(silent=True) if request.is_json else request.form
    data = data or {}
    text = str(data.get("text") or "").replace("\r\n", "\n")
    tags = parse_tags(data.get("tags"))
    stash_id = (data.get("stash_id") or "").strip()

    error = note_error(text, tags)
    if error:
        if wants_json():
            return {"error": error}, 400
        flash(error, "error")
        return redirect(url_for("main.index"))

    if stash_id:
        item = Stash.query.filter_by(id=stash_id, user_id=g.user.id).first_or_404()
        item.set_text(text)
        item.updated_at = utcnow()
    else:
        item = Stash(body=text, user_id=g.user.id)
        db.session.add(item)
        db.session.flush()
    item.tags.clear()
    for name in tags:
        item.add_tag(name)
    db.session.commit()

    if wants_json():
        return {"id": item.id, "title": item.title, "url": url_for("main.view_stash", stash_id=item.id),
                "tags": sorted(t.name for t in item.tags), "version": item.updated_at.isoformat()}, 200
    flash("Stashed.", "success")
    return redirect(url_for("main.view_stash", stash_id=item.id))


@bp.route("/stashes/<stash_id>/delete", methods=["POST"])
@login_required
def delete_stash(stash_id):
    """Throw a stash away (server side; the app itself syncs deletions)."""
    stash = Stash.query.filter_by(id=stash_id, user_id=g.user.id).first_or_404()
    toss(stash)
    db.session.commit()
    flash("Tossed it.", "success")
    return redirect(url_for("main.view_stashes"))


def _ms_to_utc(value):
    """Client timestamp (ms since epoch) -> naive UTC, never in the future."""
    try:
        moment = datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return min(moment, utcnow())


def _sync_payload(item) -> dict:
    return {
        "id": item.id,
        "text": item.body,
        "tags": sorted(t.name for t in item.tags),
        "updated_at": int(item.updated_at.replace(tzinfo=timezone.utc).timestamp() * 1000),
    }


@bp.route("/api/sync", methods=["POST"])
@login_required
@limiter.limit("240 per hour")
def sync():
    """
    Two-way sync for one device. The device sends its changes since its last
    sync ({id, text, tags, updated_at, deleted}); the newer version of each
    note wins. The reply holds every change this device hasn't seen since
    `cursor` (server write times), plus a new cursor.
    """
    data = request.get_json(silent=True) or {}
    changes = data.get("changes") or []
    if not isinstance(changes, list) or len(changes) > MAX_SYNC_CHANGES:
        return {"error": f"Send up to {MAX_SYNC_CHANGES} changes at a time."}, 400
    try:
        cursor = datetime.fromisoformat(data["cursor"]) if data.get("cursor") else None
    except (TypeError, ValueError):
        return {"error": "Bad cursor."}, 400

    started = utcnow()
    accepted, rejected = [], []
    for change in changes:
        if not isinstance(change, dict) or not UUID_RE.match(str(change.get("id", ""))):
            rejected.append({"id": change.get("id") if isinstance(change, dict) else None, "reason": "bad id"})
            continue
        note_id = change["id"]
        when = _ms_to_utc(change.get("updated_at"))
        if when is None:
            rejected.append({"id": note_id, "reason": "bad timestamp"})
            continue
        item = db.session.get(Stash, note_id)
        tomb = db.session.get(StashTombstone, note_id)
        if (item and item.user_id != g.user.id) or (tomb and tomb.user_id != g.user.id):
            rejected.append({"id": note_id, "reason": "not yours"})
            continue

        if change.get("deleted"):
            if item and item.updated_at <= when:
                toss(item)
            elif not item and not tomb:
                db.session.add(StashTombstone(stash_id=note_id, user_id=g.user.id, deleted_at=started))
            accepted.append(note_id)
            continue

        text = str(change.get("text") or "").replace("\r\n", "\n")
        tags = parse_tags(change.get("tags"))
        error = note_error(text, tags)
        if error:
            rejected.append({"id": note_id, "reason": error})
            continue
        if item and item.updated_at > when:
            accepted.append(note_id)  # the server's copy is newer; the device gets it below
            continue
        if tomb:
            if tomb.deleted_at > when:
                accepted.append(note_id)  # deleted after this edit was made
                continue
            db.session.delete(tomb)  # edited after the deletion: bring it back
        if item is None:
            item = Stash(body=text, id=note_id, user_id=g.user.id)
            db.session.add(item)
        else:
            item.set_text(text)
        item.updated_at = when
        item.tags.clear()
        for name in tags:
            item.add_tag(name)
        accepted.append(note_id)
    db.session.commit()

    stashes = Stash.query.filter_by(user_id=g.user.id)
    tombs = StashTombstone.query.filter_by(user_id=g.user.id)
    if cursor is not None:
        stashes = stashes.filter(Stash.synced_at >= cursor)
        tombs = tombs.filter(StashTombstone.deleted_at >= cursor)
    else:
        tombs = tombs.filter(db.false())  # a first sync only needs what exists
    return {
        # A few seconds of overlap so writes racing this request aren't missed
        "cursor": (started - timedelta(seconds=5)).isoformat(),
        "stashes": [_sync_payload(item) for item in stashes.all()],
        "deleted": [tomb.stash_id for tomb in tombs.all()],
        "accepted": accepted,
        "rejected": rejected,
    }, 200


# ============================================================================
# Folded notes: passed by link, open once, end-to-end encrypted
# ============================================================================

FOLD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,32}$")
B64_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")
MAX_FOLD_CIPHERTEXT = 120_000  # ~50,000 characters of text, encrypted and base64'd


@bp.route("/fold", methods=["POST"])
@login_required
@limiter.limit("60 per hour")
def fold():
    """
    Store an encrypted note for one reader. The browser encrypted it; the key
    stays in the link's #fragment, which never reaches the server.
    """
    data = request.get_json(silent=True) or {}
    ciphertext, iv = str(data.get("ciphertext") or ""), str(data.get("iv") or "")
    if not (B64_RE.match(ciphertext) and B64_RE.match(iv)) or len(iv) > 32 or len(ciphertext) > MAX_FOLD_CIPHERTEXT:
        return {"error": "That note can't be folded."}, 400
    try:
        FoldedNote.purge_expired()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Folded note cleanup failed: {e}")
    note = FoldedNote(
        id=secrets.token_urlsafe(16), sender_id=g.user.id, ciphertext=ciphertext, iv=iv,
        expires_at=utcnow() + timedelta(days=current_app.config["FOLD_TTL_DAYS"]),
    )
    db.session.add(note)
    db.session.commit()
    return {"url": url_for("main.folded", note_id=note.id, _external=True),
            "expires_at": note.expires_at.isoformat()}, 201


@bp.route("/f/<note_id>")
def folded(note_id):
    """Someone passed you a note. Opening it is a separate, deliberate step."""
    note = db.session.get(FoldedNote, note_id) if FOLD_ID_RE.match(note_id) else None
    waiting = note is not None and note.expires_at > utcnow()
    return render_template("folded.html", note_id=note_id, waiting=waiting)


@bp.route("/f/<note_id>/open", methods=["POST"])
@limiter.limit("30 per minute")
def open_folded(note_id):
    """Hand over the ciphertext exactly once: it's deleted in the same statement."""
    if not FOLD_ID_RE.match(note_id):
        return {"error": "gone"}, 404
    row = db.session.execute(
        sa_delete(FoldedNote)
        .where(FoldedNote.id == note_id, FoldedNote.expires_at > utcnow())
        .returning(FoldedNote.ciphertext, FoldedNote.iv)
    ).first()
    db.session.commit()
    if row is None:
        return {"error": "gone"}, 404
    security_log.info("Folded note opened from %s", request.remote_addr)
    return {"ciphertext": row.ciphertext, "iv": row.iv}, 200


# ============================================================================
# Pass (Recess Relay + Nearby Share) and the Teachers Lounge (settings)
# ============================================================================

@bp.route("/pass")
def pass_hub(stash_id=None):
    """Pass a note: fold one, start or join a relay, or share nearby."""
    return render_template("pass.html", stash_id=stash_id)


@bp.route("/lounge")
def lounge():
    """Teachers Lounge: theme, backup, account, about."""
    form = NameForm(obj=g.user, current_user=g.user) if g.user else None
    return render_template("lounge.html", form=form)


@bp.route("/lounge/name", methods=["POST"])
@login_required
def change_name():
    form = NameForm(current_user=g.user)
    if form.validate_on_submit():
        g.user.username = form.username.data
        db.session.commit()
        flash("Name changed.", "success")
    else:
        flash(" ".join(form.username.errors) or "That didn't work. Try again?", "error")
    return redirect(url_for("main.lounge"))


# ============================================================================
# Export/Import Routes
# ============================================================================

@bp.route("/export")
@login_required
def export_data():
    """Export all user data as JSON."""
    try:
        json_data = export_to_json(g.user)
        
        # Create file-like object
        file = BytesIO(json_data.encode('utf-8'))
        file.seek(0)
        
        logger.info(f"Data exported for user {g.user.username}")
        
        return send_file(
            file,
            mimetype='application/json',
            as_attachment=True,
            download_name=f'ruff-export-{g.user.username}.json'
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting data: {str(e)}")
        flash("Couldn't make the backup. Try again?", "error")
        return redirect(url_for("main.index"))


@bp.route("/export/stash/<stash_id>")
@login_required
def export_stash(stash_id):
    """Export a single stash as text."""
    try:
        stash = Stash.query.filter_by(id=stash_id, user_id=g.user.id).first_or_404()
        
        text_data = export_stash_to_text(stash)
        
        # Create file-like object
        file = BytesIO(text_data.encode('utf-8'))
        file.seek(0)
        
        logger.info(f"Stash {stash_id} exported for user {g.user.username}")
        
        return send_file(
            file,
            mimetype='text/plain',
            as_attachment=True,
            download_name=f'stash-{safe_filename_part(stash.title or stash.preview)}.txt'
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting stash: {str(e)}")
        flash("Couldn't download that. Try again?", "error")
        return redirect(url_for("main.view_stashes"))


# ============================================================================
# Nearby Share Routes (WebRTC data channel)
# ============================================================================

@bp.route("/share")
@login_required
def share():
    """Nearby Share lives on the Pass page."""
    return redirect(url_for("main.pass_hub"))


@bp.route("/share/<stash_id>")
@login_required
def share_stash(stash_id):
    """The Pass page with this note ready to send."""
    if not UUID_RE.match(stash_id):
        abort(404)
    return pass_hub(stash_id=stash_id)


@bp.route("/share/payload/<stash_id>")
@login_required
def share_payload(stash_id):
    """Provide stash payload for nearby sharing."""
    stash = Stash.query.filter_by(id=stash_id, user_id=g.user.id).first_or_404()
    return {
        "id": stash.id,
        "title": stash.title,
        "body": stash.body,
        "checklist": stash.get_checklist(),
        "tags": [tag.name for tag in stash.tags],
    }, 200


@bp.route("/share/import", methods=["POST"])
@login_required
def import_shared_stash():
    """Import a shared stash payload into the current user's account."""
    try:
        data = request.get_json() or {}
        title = (data.get("title") or "").strip()
        body = (data.get("body") or "").strip()
        checklist_items = data.get("checklist")
        if not isinstance(checklist_items, list):
            checklist_items = []

        if not body:
            return {"error": "Missing body"}, 400
        if len(body) > current_app.config["MAX_STASH_LENGTH"]:
            return {"error": "Stash body is too long"}, 400
        if len(title) > MAX_TITLE_LENGTH:
            return {"error": "Stash title is too long"}, 400

        tag_names = data.get("tags") or []
        if not isinstance(tag_names, list) or not all(
            isinstance(name, str) and 0 < len(name.strip()) <= MAX_TAG_LENGTH
            for name in tag_names
        ):
            return {"error": "Invalid tags"}, 400

        new_stash = Stash(
            title=title or None,
            body=body,
            checklist=checklist_items,
            user_id=g.user.id,
        )
        db.session.add(new_stash)
        db.session.flush()

        for tag_name in tag_names:
            new_stash.add_tag(tag_name.strip())

        db.session.commit()
        logger.info(f"Shared stash imported for user {g.user.username}: {new_stash.id}")
        return {"success": True, "id": new_stash.id}, 200
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error importing shared stash: {str(e)}")
        return {"error": "Failed to import shared stash"}, 500


# ============================================================================
# Recess Relay Routes
# ============================================================================

@bp.route("/relay", methods=["GET", "POST"])
def relay_home():
    """Join or start a Recess Relay."""
    if request.method == "GET":
        return redirect(url_for("main.pass_hub"))

    action = (request.form.get("action") or "").strip()
    if action == "join":
        code = (request.form.get("code") or "").strip().upper()
        if not code:
            flash("Type the relay code to join.", "warning")
            return redirect(url_for("main.pass_hub"))
        return redirect(url_for("main.relay_view", code=code))

    if action == "start":
        if g.user is None:
            flash("Log in to start a relay. Anyone can join one.", "warning")
            return redirect(url_for("main.login"))

        title = (request.form.get("title") or "").strip() or "Recess Relay"
        prompt = (request.form.get("prompt") or "").strip()
        max_entries_raw = (request.form.get("max_entries") or "").strip()
        try:
            max_entries = int(max_entries_raw) if max_entries_raw else 8
        except ValueError:
            max_entries = 8
        max_entries = max(3, min(max_entries, 20))

        purge_expired_relays()
        code = generate_relay_code()
        while RelaySession.query.filter_by(code=code).first():
            code = generate_relay_code()

        relay = RelaySession(
            code=code,
            owner_id=g.user.id,
            title=title,
            prompt=prompt or None,
            max_entries=max_entries,
        )
        db.session.add(relay)
        db.session.commit()
        flash(f"Relay started. Give friends the code {relay.code}.", "success")
        return redirect(url_for("main.relay_view", code=relay.code))

    flash("That didn't work. Try again?", "error")
    return redirect(url_for("main.relay_home"))


@bp.route("/relay/start/<stash_id>", methods=["POST"])
@login_required
def relay_start_from_stash(stash_id):
    """Start a relay from an existing stash."""
    stash = Stash.query.filter_by(id=stash_id, user_id=g.user.id).first_or_404()
    title = stash.title or "Recess Relay"
    prompt = stash.body or ""

    purge_expired_relays()
    code = generate_relay_code()
    while RelaySession.query.filter_by(code=code).first():
        code = generate_relay_code()

    relay = RelaySession(
        code=code,
        owner_id=g.user.id,
        title=title,
        prompt=prompt,
        max_entries=8,
    )
    db.session.add(relay)
    db.session.commit()
    flash(f"Relay started. Give friends the code {relay.code}.", "success")
    return redirect(url_for("main.relay_view", code=relay.code))


@bp.route("/relay/<code>")
def relay_view(code):
    """View a relay session."""
    relay = get_active_relay_or_404(code)
    entries = relay.entries
    entry_count = len(entries)
    can_add = (not relay.is_closed) and entry_count < relay.max_entries
    is_owner = g.user is not None and g.user.id == relay.owner_id
    return render_template(
        "relay.html",
        relay=relay,
        entries=entries,
        can_add=can_add,
        is_owner=is_owner,
        entry_count=entry_count,
    )


@bp.route("/relay/<code>/add", methods=["POST"])
def relay_add(code):
    """Add a line to a relay session."""
    relay = get_active_relay_or_404(code)
    if relay.is_closed:
        flash("This relay is closed.", "warning")
        return redirect(url_for("main.relay_view", code=relay.code))

    body = (request.form.get("body") or "").strip()
    if not body:
        flash("Write your line first.", "warning")
        return redirect(url_for("main.relay_view", code=relay.code))
    if len(body) > 240:
        flash("Keep it to one line (240 characters).", "warning")
        return redirect(url_for("main.relay_view", code=relay.code))

    entry_count = db.session.query(func.max(RelayEntry.position)).filter_by(session_id=relay.id).scalar() or 0
    if entry_count >= relay.max_entries:
        flash("The note's full.", "warning")
        return redirect(url_for("main.relay_view", code=relay.code))

    author = g.user.username if g.user else (request.form.get("author_name") or "Guest").strip()
    if not author:
        author = "Guest"

    entry = RelayEntry(
        session_id=relay.id,
        author_name=author[:80],
        body=body,
        position=entry_count + 1,
    )
    db.session.add(entry)
    db.session.commit()
    return redirect(url_for("main.relay_view", code=relay.code))


@bp.route("/relay/<code>/close", methods=["POST"])
@login_required
def relay_close(code):
    """Close a relay session."""
    relay = get_active_relay_or_404(code)
    if relay.owner_id != g.user.id:
        flash("Only whoever started the relay can close it.", "error")
        return redirect(url_for("main.relay_view", code=relay.code))

    relay.is_closed = True
    relay.closed_at = utcnow()
    db.session.commit()
    flash("Relay closed. That's the end of the story.", "success")
    return redirect(url_for("main.relay_view", code=relay.code))


@bp.route("/import", methods=["GET", "POST"])
@login_required
def import_data():
    """Restore stashes and tags from a backup file."""
    if request.method == "GET":
        return redirect(url_for("main.lounge", _anchor="backup"))
    
    try:
        # Check if file was uploaded
        if 'file' not in request.files:
            flash("Pick a backup file first.", "warning")
            return redirect(url_for("main.lounge", _anchor="backup"))
        
        file = request.files['file']
        
        if file.filename == '':
            flash("Pick a backup file first.", "warning")
            return redirect(url_for("main.lounge", _anchor="backup"))
        
        if not file.filename.endswith('.json'):
            flash("That isn't a backup file (it should end in .json).", "error")
            return redirect(url_for("main.lounge", _anchor="backup"))
        
        # Read file content
        try:
            json_content = file.read().decode('utf-8')
        except UnicodeDecodeError:
            flash("That file couldn't be read. Is it a backup from here?", "error")
            return redirect(url_for("main.lounge", _anchor="backup"))
        
        # Import data
        result = import_from_json(g.user, json_content)
        
        if not result['success']:
            flash(f"Couldn't restore that: {result['error']}", "error")
            return redirect(url_for("main.lounge", _anchor="backup"))
        
        # Show success message with statistics
        created = result['created']['stashes']
        message = f"Restored {created} stash{'' if created == 1 else 'es'}."
        if result['skipped']['stashes'] > 0:
            message += f" {result['skipped']['stashes']} were already here."
        if result['skipped']['too_large'] > 0:
            message += f" {result['skipped']['too_large']} were too long to keep."
        
        logger.info(f"Data imported for user {g.user.username}: {result}")
        flash(message, "success")
        return redirect(url_for("main.view_stashes"))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error importing data: {str(e)}")
        flash("Couldn't restore that file. Try again?", "error")
        return redirect(url_for("main.lounge", _anchor="backup"))
