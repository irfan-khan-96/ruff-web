"""
Route handlers for the Ruff application.
"""

import logging
import os
import json
import secrets
import string
from datetime import datetime
from functools import wraps
from flask import Blueprint, render_template, session, redirect, url_for, flash, current_app, request, g, send_file, send_from_directory
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import or_, text, func
from io import BytesIO

from forms import (
    StashForm,
    EditStashForm,
    CollectionForm,
    LoginForm,
    SignupForm,
    ResendVerificationForm,
    ForgotPasswordForm,
    ResetPasswordForm,
)
from models import db, Stash, Tag, Collection, User, RelaySession, RelayEntry
from export_import import export_to_json, export_stash_to_text, import_from_json
from auth_utils import generate_token, verify_token, send_email

logger = logging.getLogger(__name__)

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
    """Readiness check that validates DB connectivity."""
    try:
        # Minimal DB check
        db.session.execute(text("SELECT 1"))
        return {"status": "ok"}, 200
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return {"status": "error", "reason": str(e)}, 503


@bp.route("/sw.js")
def service_worker():
    """Serve the service worker at the app root."""
    return send_from_directory(current_app.static_folder, "sw.js")


def login_required(f):
    """Decorator to require login for a route."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('You must be logged in to access this page.', 'warning')
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return decorated_function


@bp.before_request
def load_logged_in_user():
    """Load the logged-in user from session."""
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        g.user = db.session.get(User, user_id)
        if (
            g.user
            and current_app.config.get("REQUIRE_EMAIL_VERIFICATION", True)
            and not g.user.email_verified
        ):
            session.clear()
            g.user = None


def get_collection_choices():
    """Get all collections for current user."""
    try:
        if g.user is None:
            return []
        return [(c.id, c.name) for c in Collection.query.filter_by(user_id=g.user.id).all()]
    except Exception as e:
        logger.error(f"Error fetching collections: {e}")
        return []


def get_user_tags_with_counts(user_id: int):
    """Return tags for a user with stash counts."""
    rows = (
        db.session.query(Tag, func.count(Stash.id))
        .join(Tag.stashes)
        .filter(Stash.user_id == user_id)
        .group_by(Tag.id)
        .order_by(Tag.name)
        .all()
    )
    return [
        {"id": tag.id, "name": tag.name, "stash_count": count}
        for tag, count in rows
    ]


def get_user_collections_with_counts(user_id: int):
    """Return collections for a user with stash counts."""
    rows = (
        db.session.query(Collection, func.count(Stash.id))
        .outerjoin(
            Stash,
            (Stash.collection_id == Collection.id) & (Stash.user_id == user_id),
        )
        .filter(Collection.user_id == user_id)
        .group_by(Collection.id)
        .order_by(Collection.created_at.desc())
        .all()
    )
    return [
        {
            "id": collection.id,
            "name": collection.name,
            "description": collection.description,
            "stash_count": count,
            "created_at": collection.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        }
        for collection, count in rows
    ]


def generate_relay_code(length: int = 6) -> str:
    """Generate a short uppercase relay code."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def parse_checklist(raw: str):
    """Parse checklist JSON into a normalized list of dicts."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    items = []
    for item in data:
        if isinstance(item, dict):
            text = str(item.get("text", "")).strip()
            done = bool(item.get("done", False))
        else:
            text = str(item).strip()
            done = False
        if text:
            items.append({"text": text, "done": done})
    return items


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    """Handle user login."""
    if g.user is not None:
        return redirect(url_for("main.index"))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        
        if user is None or not user.check_password(form.password.data):
            flash("Invalid username or password.", "danger")
            return redirect(url_for("main.login"))

        if current_app.config.get("REQUIRE_EMAIL_VERIFICATION", True) and not user.email_verified:
            flash("Please verify your email before logging in.", "warning")
            return redirect(url_for("main.resend_verification", email=user.email))
        
        session.clear()
        session['user_id'] = user.id
        session.permanent = bool(form.remember.data)
        logger.info(f"User {user.username} logged in")
        flash(f"Welcome back, {user.username}!", "success")
        return redirect(url_for("main.index"))
    
    return render_template("login.html", form=form)


@bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def signup():
    """Handle user registration."""
    if g.user is not None:
        return redirect(url_for("main.index"))
    
    form = SignupForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data.strip(),
            email=form.email.data.strip().lower()
        )
        user.set_password(form.password.data)
        
        try:
            db.session.add(user)
            db.session.commit()
            logger.info(f"New user registered: {user.username}")
            token = generate_token(user, "email_verify")
            verify_url = url_for("main.verify_email", token=token, _external=True)
            send_email(
                user.email,
                "Verify your Ruff account",
                f"Verify your email: {verify_url}",
            )
            flash("Account created! Check your email to verify before logging in.", "success")
            return redirect(url_for("main.login"))
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            flash("An error occurred during registration. Please try again.", "danger")
            db.session.rollback()
    
    return render_template("signup.html", form=form)


@bp.route("/logout")
def logout():
    """Handle user logout."""
    if g.user is not None:
        logger.info(f"User {g.user.username} logged out")
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.login"))


@bp.route("/verify/<token>")
def verify_email(token):
    """Verify a user's email address."""
    user, error = verify_token(
        token,
        "email_verify",
        current_app.config.get("EMAIL_VERIFY_TOKEN_EXP", 86400),
    )
    if error:
        flash("Verification link is invalid or expired.", "danger")
        return redirect(url_for("main.resend_verification"))

    if not user.email_verified:
        user.email_verified = True
        user.email_verified_at = datetime.utcnow()
        db.session.commit()
        flash("Email verified! You can now log in.", "success")
    else:
        flash("Email already verified. Please log in.", "info")
    return redirect(url_for("main.login"))


@bp.route("/verify/resend", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def resend_verification():
    """Resend verification email."""
    form = ResendVerificationForm()
    if request.method == "GET" and request.args.get("email"):
        form.email.data = request.args.get("email")
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.strip().lower()).first()
        if user and not user.email_verified:
            token = generate_token(user, "email_verify")
            verify_url = url_for("main.verify_email", token=token, _external=True)
            send_email(
                user.email,
                "Verify your Ruff account",
                f"Verify your email: {verify_url}",
            )
        flash("If the account exists, a verification link has been sent.", "info")
        return redirect(url_for("main.login"))
    return render_template("resend_verification.html", form=form)


@bp.route("/password/forgot", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def forgot_password():
    """Request a password reset email."""
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.strip().lower()).first()
        if user:
            token = generate_token(user, "password_reset")
            reset_url = url_for("main.reset_password", token=token, _external=True)
            send_email(
                user.email,
                "Reset your Ruff password",
                f"Reset your password: {reset_url}",
            )
        flash("If the account exists, a reset link has been sent.", "info")
        return redirect(url_for("main.login"))
    return render_template("forgot_password.html", form=form)


@bp.route("/password/reset/<token>", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def reset_password(token):
    """Reset a user's password."""
    user, error = verify_token(
        token,
        "password_reset",
        current_app.config.get("PASSWORD_RESET_TOKEN_EXP", 3600),
    )
    if error:
        flash("Password reset link is invalid or expired.", "danger")
        return redirect(url_for("main.forgot_password"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash("Password reset successfully. Please log in.", "success")
        return redirect(url_for("main.login"))
    return render_template("reset_password.html", form=form)


@bp.route("/")
@login_required
def index():
    """Render the home page with stash creation form."""
    form = StashForm()
    form.collection.choices = [(-1, "-- No Collection --")] + get_collection_choices()
    return render_template("index.html", form=form)


@bp.route("/stash", methods=["POST"])
@login_required
def stash():
    """Handle stash creation."""
    form = StashForm()
    form.collection.choices = [(-1, "-- No Collection --")] + get_collection_choices()
    
    if form.validate_on_submit():
        try:
            title = form.title.data
            body = form.body.data
            checklist_items = parse_checklist(form.checklist.data)
            
            # Get collection if selected
            collection_id = None
            if form.collection.data and form.collection.data != -1:
                collection_id = form.collection.data
            
            new_stash = Stash(
                title=title,
                body=body,
                checklist=checklist_items,
                user_id=g.user.id,
                collection_id=collection_id
            )
            db.session.add(new_stash)
            db.session.flush()
            
            # Add tags if provided
            if form.tags.data:
                tags = [tag.strip().lower() for tag in form.tags.data.split(',') if tag.strip()]
                for tag_name in tags:
                    new_stash.add_tag(tag_name)
            
            db.session.commit()
            
            flash("Stash saved successfully!", "success")
            logger.info(f"New stash created: {new_stash.id}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating stash: {str(e)}")
            flash("Failed to save stash. Please try again.", "error")
    else:
        flash("Failed to save stash. Please check your input.", "error")
    return redirect(url_for("main.index"))


@bp.route("/stashes")
@login_required
def view_stashes():
    """Display all stashes with optional filtering."""
    try:
        # Get filter parameters
        collection_id = request.args.get('collection', type=int)
        tag_name = request.args.get('tag', type=str)
        search_query = request.args.get('search', type=str)
        
        # Build query - filter by current user
        query = Stash.query.filter_by(user_id=g.user.id)
        
        if collection_id:
            query = query.filter_by(collection_id=collection_id)
        
        if tag_name:
            query = query.join(Stash.tags).filter(Tag.name == tag_name.lower())
        
        if search_query:
            search_pattern = f"%{search_query}%"
            query = query.filter(
                or_(
                    Stash.title.ilike(search_pattern),
                    Stash.body.ilike(search_pattern),
                    Stash.preview.ilike(search_pattern)
                )
            )
        
        stashes = query.order_by(Stash.created_at.desc()).all()
        
        # Get all collections and tags for sidebar - filtered by current user
        collection_dicts = get_user_collections_with_counts(g.user.id)
        tags = get_user_tags_with_counts(g.user.id)
        
        return render_template(
            "stashes.html",
            stashes=[s.to_dict() for s in stashes],
            collections=collection_dicts,
            tags=tags,
            current_collection=collection_id,
            current_tag=tag_name,
            search_query=search_query
        )
    except Exception as e:
        logger.error(f"Error loading stashes: {str(e)}")
        flash("An error occurred while loading stashes.", "error")
        return redirect(url_for("main.index"))


@bp.route("/stashes/<stash_id>")
@login_required
def view_stash(stash_id):
    """Display a specific stash."""
    try:
        stash = Stash.query.filter_by(id=stash_id, user_id=g.user.id).first_or_404()
        return render_template("viewstash.html", stash=stash.to_dict())
    except Exception as e:
        logger.error(f"Error loading stash {stash_id}: {str(e)}")
        flash("An error occurred while loading the stash.", "error")
        return redirect(url_for("main.view_stashes"))


@bp.route("/stashes/<stash_id>/checklist", methods=["POST"])
@login_required
def update_checklist(stash_id):
    """Update checklist items for a stash."""
    try:
        stash = Stash.query.filter_by(id=stash_id, user_id=g.user.id).first_or_404()
        payload = request.get_json(silent=True) or {}
        items = payload.get("checklist")
        if not isinstance(items, list):
            return {"error": "Invalid checklist"}, 400
        stash.set_checklist(items)
        db.session.commit()
        return {"success": True}, 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating checklist {stash_id}: {str(e)}")
        return {"error": "Failed to update checklist"}, 500


@bp.route("/stashes/<stash_id>/edit", methods=["GET", "POST"])
@login_required
def edit_stash(stash_id):
    """Handle stash editing."""
    try:
        stash = Stash.query.filter_by(id=stash_id, user_id=g.user.id).first_or_404()
        
        form = EditStashForm()
        form.collection.choices = [(-1, "-- No Collection --")] + get_collection_choices()
        
        if form.validate_on_submit():
            try:
                stash.title = form.title.data.strip() if form.title.data else None
                stash.body = form.body.data
                stash.update_preview()
                stash.set_checklist(parse_checklist(form.checklist.data))
                
                # Update collection
                if form.collection.data and form.collection.data != -1:
                    stash.collection_id = form.collection.data
                else:
                    stash.collection_id = None
                
                # Update tags
                stash.tags.clear()
                if form.tags.data:
                    tags = [tag.strip().lower() for tag in form.tags.data.split(',') if tag.strip()]
                    for tag_name in tags:
                        stash.add_tag(tag_name)
                
                db.session.commit()
                flash("Stash updated successfully!", "success")
                logger.info(f"Stash updated: {stash_id}")
                return redirect(url_for("main.view_stashes"))
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error updating stash {stash_id}: {str(e)}")
                flash("Failed to update stash. Please try again.", "error")
        
        form.title.data = stash.title or ""
        form.body.data = stash.body
        form.collection.data = stash.collection_id or -1
        form.tags.data = ', '.join([tag.name for tag in stash.tags])
        form.checklist.data = json.dumps(stash.get_checklist())
        
        return render_template("editstash.html", form=form, stash=stash.to_dict())
    except Exception as e:
        logger.error(f"Error in edit_stash {stash_id}: {str(e)}")
        flash("An error occurred while editing the stash.", "error")
        return redirect(url_for("main.view_stashes"))


@bp.route("/stashes/<stash_id>/delete", methods=["POST"])
@login_required
def delete_stash(stash_id):
    """Handle stash deletion."""
    try:
        stash = Stash.query.filter_by(id=stash_id, user_id=g.user.id).first()
        
        if stash is None:
            logger.warning(f"Stash not found for deletion: {stash_id}")
            flash("Stash not found.", "error")
        else:
            db.session.delete(stash)
            db.session.commit()
            flash("Stash deleted successfully!", "success")
            logger.info(f"Stash deleted: {stash_id}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting stash {stash_id}: {str(e)}")
        flash("Failed to delete stash. Please try again.", "error")
    
    return redirect(url_for("main.view_stashes"))


# Collection Routes
@bp.route("/collections")
@login_required
def view_collections():
    """Display all collections."""
    try:
        collections = get_user_collections_with_counts(g.user.id)
        return render_template("collections.html", collections=collections)
    except Exception as e:
        logger.error(f"Error loading collections: {str(e)}")
        flash("An error occurred while loading collections.", "error")
        return redirect(url_for("main.index"))


@bp.route("/collections/new", methods=["GET", "POST"])
@login_required
def create_collection():
    """Create a new collection."""
    form = CollectionForm()
    if form.validate_on_submit():
        try:
            # Check if collection name already exists
            existing = Collection.query.filter_by(name=form.name.data, user_id=g.user.id).first()
            if existing:
                flash("A collection with this name already exists.", "error")
                return redirect(url_for("main.create_collection"))
            
            new_collection = Collection(
                user_id=g.user.id,
                name=form.name.data,
                description=form.description.data or None
            )
            db.session.add(new_collection)
            db.session.commit()
            
            flash(f"Collection '{form.name.data}' created successfully!", "success")
            logger.info(f"New collection created: {new_collection.id}")
            return redirect(url_for("main.view_collections"))
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating collection: {str(e)}")
            flash("Failed to create collection. Please try again.", "error")
    
    return render_template("create_collection.html", form=form)


@bp.route("/collections/<int:collection_id>/delete", methods=["POST"])
@login_required
def delete_collection(collection_id):
    """Delete a collection."""
    try:
        collection = Collection.query.filter_by(id=collection_id, user_id=g.user.id).first()
        
        if collection is None:
            flash("Collection not found.", "error")
        else:
            # Remove stashes from collection (but don't delete stashes)
            for stash in collection.stashes:
                stash.collection_id = None
            
            db.session.delete(collection)
            db.session.commit()
            flash(f"Collection '{collection.name}' deleted successfully!", "success")
            logger.info(f"Collection deleted: {collection_id}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting collection {collection_id}: {str(e)}")
        flash("Failed to delete collection. Please try again.", "error")
    
    return redirect(url_for("main.view_collections"))


# Tag Routes
@bp.route("/tags")
@login_required
def view_tags():
    """Display all tags."""
    try:
        tags = get_user_tags_with_counts(g.user.id)
        return render_template("tags.html", tags=tags)
    except Exception as e:
        logger.error(f"Error loading tags: {str(e)}")
        flash("An error occurred while loading tags.", "error")
        return redirect(url_for("main.index"))


@bp.route("/tags/<int:tag_id>/delete", methods=["POST"])
@login_required
def delete_tag(tag_id):
    """Delete a tag."""
    try:
        tag = db.session.get(Tag, tag_id)
        
        if tag is None:
            flash("Tag not found.", "error")
        else:
            # Only allow tag removal for stashes owned by current user
            user_stashes = (
                Stash.query.join(Stash.tags)
                .filter(Tag.id == tag_id, Stash.user_id == g.user.id)
                .all()
            )

            if not user_stashes:
                flash("Tag not found or access denied.", "error")
                return redirect(url_for("main.view_tags"))

            for stash in user_stashes:
                stash.remove_tag(tag)

            # Delete the tag only if it's no longer used by any stash
            if len(tag.stashes) == 0:
                tag_name = tag.name
                db.session.delete(tag)
                flash(f"Tag '{tag_name}' deleted successfully!", "success")
                logger.info(f"Tag deleted: {tag_id}")
            else:
                flash("Tag removed from your stashes.", "success")
                logger.info(f"Tag removed from user stashes: {tag_id}")

            db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting tag {tag_id}: {str(e)}")
        flash("Failed to delete tag. Please try again.", "error")
    
    return redirect(url_for("main.view_tags"))


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
    except Exception as e:
        logger.error(f"Error exporting data: {str(e)}")
        flash("Failed to export data. Please try again.", "error")
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
            download_name=f'stash-{stash.preview[:20]}.txt'
        )
    except Exception as e:
        logger.error(f"Error exporting stash: {str(e)}")
        flash("Failed to export stash. Please try again.", "error")
        return redirect(url_for("main.view_stashes"))


# ============================================================================
# Nearby Share Routes (WebRTC data channel)
# ============================================================================

@bp.route("/share")
@login_required
def share():
    """Render the nearby share page."""
    return render_template("share.html", stash=None)


@bp.route("/share/<stash_id>")
@login_required
def share_stash(stash_id):
    """Render the nearby share page for a specific stash."""
    stash = Stash.query.filter_by(id=stash_id, user_id=g.user.id).first_or_404()
    return render_template("share.html", stash=stash.to_dict())


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
        "collection": stash.collection.name if stash.collection else None,
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

        new_stash = Stash(
            title=title or None,
            body=body,
            checklist=checklist_items,
            user_id=g.user.id,
            collection_id=None,
        )
        db.session.add(new_stash)
        db.session.flush()

        for tag_name in data.get("tags", []) or []:
            new_stash.add_tag(tag_name)

        db.session.commit()
        logger.info(f"Shared stash imported for user {g.user.username}: {new_stash.id}")
        return {"success": True, "id": new_stash.id}, 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error importing shared stash: {str(e)}")
        return {"error": str(e)}, 500


# ============================================================================
# Recess Relay Routes
# ============================================================================

@bp.route("/relay", methods=["GET", "POST"])
def relay_home():
    """Join or start a Recess Relay."""
    if request.method == "GET":
        return render_template("relay_home.html")

    action = (request.form.get("action") or "").strip()
    if action == "join":
        code = (request.form.get("code") or "").strip().upper()
        if not code:
            flash("Enter a relay code to join.", "warning")
            return redirect(url_for("main.relay_home"))
        return redirect(url_for("main.relay_view", code=code))

    if action == "start":
        if g.user is None:
            flash("Login required to start a relay.", "warning")
            return redirect(url_for("main.login"))

        title = (request.form.get("title") or "").strip() or "Recess Relay"
        prompt = (request.form.get("prompt") or "").strip()
        max_entries_raw = (request.form.get("max_entries") or "").strip()
        try:
            max_entries = int(max_entries_raw) if max_entries_raw else 8
        except ValueError:
            max_entries = 8
        max_entries = max(3, min(max_entries, 20))

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
        flash(f"Relay started. Share code {relay.code}.", "success")
        return redirect(url_for("main.relay_view", code=relay.code))

    flash("Invalid relay action.", "error")
    return redirect(url_for("main.relay_home"))


@bp.route("/relay/start/<stash_id>", methods=["POST"])
@login_required
def relay_start_from_stash(stash_id):
    """Start a relay from an existing stash."""
    stash = Stash.query.filter_by(id=stash_id, user_id=g.user.id).first_or_404()
    title = stash.title or "Recess Relay"
    prompt = stash.body or ""

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
    flash(f"Relay started. Share code {relay.code}.", "success")
    return redirect(url_for("main.relay_view", code=relay.code))


@bp.route("/relay/<code>")
def relay_view(code):
    """View a relay session."""
    relay = RelaySession.query.filter_by(code=code.upper()).first_or_404()
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
    relay = RelaySession.query.filter_by(code=code.upper()).first_or_404()
    if relay.is_closed:
        flash("This relay is closed.", "warning")
        return redirect(url_for("main.relay_view", code=relay.code))

    body = (request.form.get("body") or "").strip()
    if not body:
        flash("Add a line before submitting.", "warning")
        return redirect(url_for("main.relay_view", code=relay.code))
    if len(body) > 240:
        flash("Keep it short — max 240 characters per line.", "warning")
        return redirect(url_for("main.relay_view", code=relay.code))

    entry_count = db.session.query(func.max(RelayEntry.position)).filter_by(session_id=relay.id).scalar() or 0
    if entry_count >= relay.max_entries:
        flash("This relay already hit its limit.", "warning")
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
    relay = RelaySession.query.filter_by(code=code.upper()).first_or_404()
    if relay.owner_id != g.user.id:
        flash("Only the relay owner can close it.", "error")
        return redirect(url_for("main.relay_view", code=relay.code))

    relay.is_closed = True
    relay.closed_at = datetime.utcnow()
    db.session.commit()
    flash("Relay closed.", "success")
    return redirect(url_for("main.relay_view", code=relay.code))


@bp.route("/import", methods=["GET", "POST"])
@login_required
def import_data():
    """Import stashes, collections, and tags from JSON."""
    if request.method == "GET":
        return render_template("import.html")
    
    try:
        # Check if file was uploaded
        if 'file' not in request.files:
            flash("No file selected. Please choose a file to import.", "warning")
            return redirect(url_for("main.import_data"))
        
        file = request.files['file']
        
        if file.filename == '':
            flash("No file selected. Please choose a file to import.", "warning")
            return redirect(url_for("main.import_data"))
        
        if not file.filename.endswith('.json'):
            flash("Invalid file type. Please upload a JSON file.", "error")
            return redirect(url_for("main.import_data"))
        
        # Read file content
        try:
            json_content = file.read().decode('utf-8')
        except UnicodeDecodeError:
            flash("File encoding error. Please make sure the file is UTF-8 encoded.", "error")
            return redirect(url_for("main.import_data"))
        
        # Import data
        result = import_from_json(g.user, json_content)
        
        if not result['success']:
            flash(f"Import failed: {result['error']}", "error")
            return redirect(url_for("main.import_data"))
        
        # Show success message with statistics
        message = (
            f"✓ Import successful! "
            f"Created: {result['created']['collections']} collections, "
            f"{result['created']['stashes']} stashes, "
            f"{result['created']['tags']} tags. "
        )
        
        if result['skipped']['stashes'] > 0:
            message += f"(Skipped {result['skipped']['stashes']} existing stashes)"
        
        logger.info(f"Data imported for user {g.user.username}: {result}")
        flash(message, "success")
        return redirect(url_for("main.view_stashes"))
    
    except Exception as e:
        logger.error(f"Error importing data: {str(e)}")
        flash(f"Import failed: {str(e)}", "error")
        return redirect(url_for("main.import_data"))


@bp.route("/stash/bulk/delete", methods=["POST"])
@login_required
def bulk_delete():
    """Delete multiple stashes at once."""
    try:
        data = request.get_json(silent=True) or {}
        stash_ids = data.get('stash_ids', [])
        
        if not stash_ids:
            return {"error": "No stashes selected"}, 400
        
        # Validate that all stashes belong to the current user
        stashes_to_delete = Stash.query.filter(
            Stash.id.in_(stash_ids),
            Stash.user_id == g.user.id
        ).all()
        
        deleted_count = len(stashes_to_delete)
        
        if deleted_count != len(stash_ids):
            # Some stashes don't belong to this user or don't exist
            logger.warning(f"User {g.user.id} attempted to delete {len(stash_ids)} stashes but only {deleted_count} belong to them")
        
        # Delete all validated stashes
        for stash in stashes_to_delete:
            db.session.delete(stash)
        
        db.session.commit()
        logger.info(f"User {g.user.username} deleted {deleted_count} stashes via bulk action")
        
        return {"success": True, "deleted": deleted_count}, 200
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in bulk delete: {str(e)}")
        return {"error": str(e)}, 500


@bp.route("/stash/bulk/move", methods=["POST"])
@login_required
def bulk_move():
    """Move multiple stashes to a collection."""
    try:
        data = request.get_json(silent=True) or {}
        stash_ids = data.get('stash_ids', [])
        collection_id = data.get('collection_id')
        
        if not stash_ids:
            return {"error": "No stashes selected"}, 400
        
        # Validate that all stashes belong to the current user
        stashes_to_move = Stash.query.filter(
            Stash.id.in_(stash_ids),
            Stash.user_id == g.user.id
        ).all()
        
        moved_count = len(stashes_to_move)
        
        if moved_count != len(stash_ids):
            logger.warning(f"User {g.user.id} attempted to move {len(stash_ids)} stashes but only {moved_count} belong to them")
        
        # If collection_id is provided, validate it belongs to the user
        if collection_id:
            collection = Collection.query.filter_by(
                id=collection_id,
                user_id=g.user.id
            ).first()
            
            if not collection:
                return {"error": "Collection not found or you don't have permission to use it"}, 403
        
        # Move all validated stashes
        for stash in stashes_to_move:
            stash.collection_id = collection_id
        
        db.session.commit()
        logger.info(f"User {g.user.username} moved {moved_count} stashes via bulk action")
        
        return {"success": True, "moved": moved_count}, 200
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in bulk move: {str(e)}")
        return {"error": str(e)}, 500
