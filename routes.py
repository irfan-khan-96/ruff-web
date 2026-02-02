"""
Route handlers for the Ruff application.
"""

import uuid
import logging
from functools import wraps
from flask import Blueprint, render_template, session, redirect, url_for, flash, current_app, request, g, send_file
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import or_, text
from io import BytesIO

from forms import StashForm, EditStashForm, CollectionForm, SearchForm, LoginForm, SignupForm
from models import db, Stash, Tag, Collection, User
from utils import create_stash_dict, sanitize_stash_data
from export_import import export_to_json, export_stash_to_text, import_from_json

logger = logging.getLogger(__name__)

bp = Blueprint("main", __name__)
csrf = CSRFProtect()


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
        g.user = User.query.get(user_id)


def get_collection_choices():
    """Get all collections for current user."""
    try:
        if g.user is None:
            return []
        return [(c.id, c.name) for c in Collection.query.filter_by(user_id=g.user.id).all()]
    except Exception as e:
        logger.error(f"Error fetching collections: {e}")
        return []


def get_tag_choices():
    """Get all tags for form choices."""
    try:
        return [(t.id, t.name) for t in Tag.query.all()]
    except Exception as e:
        logger.error(f"Error fetching tags: {e}")
        return []


@bp.route("/login", methods=["GET", "POST"])
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
        
        session.clear()
        session['user_id'] = user.id
        logger.info(f"User {user.username} logged in")
        flash(f"Welcome back, {user.username}!", "success")
        return redirect(url_for("main.index"))
    
    return render_template("login.html", form=form)


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    """Handle user registration."""
    if g.user is not None:
        return redirect(url_for("main.index"))
    
    form = SignupForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data
        )
        user.set_password(form.password.data)
        
        try:
            db.session.add(user)
            db.session.commit()
            logger.info(f"New user registered: {user.username}")
            flash("Account created successfully! Please log in.", "success")
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


@bp.route("/")
@login_required
def index():
    """Render the home page with stash creation form."""
    form = StashForm()
    form.collection.choices = [(-1, "-- No Collection --")] + get_collection_choices()
    saved_text = session.get("saved_text", "")
    return render_template("index.html", form=form, saved_text=saved_text)


@bp.route("/stash", methods=["POST"])
@login_required
def stash():
    """Handle stash creation."""
    form = StashForm()
    form.collection.choices = [(-1, "-- No Collection --")] + get_collection_choices()
    
    if form.validate_on_submit():
        try:
            text = form.text.data
            stash_id = str(uuid.uuid4())
            preview = text[:50] + ('...' if len(text) > 50 else '')
            
            # Get collection if selected
            collection_id = None
            if form.collection.data and form.collection.data != -1:
                collection_id = form.collection.data
            
            new_stash = Stash(
                id=stash_id,
                text=text,
                preview=preview,
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
            logger.info(f"New stash created: {stash_id}")
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
                    Stash.text.ilike(search_pattern),
                    Stash.preview.ilike(search_pattern)
                )
            )
        
        stashes = query.order_by(Stash.created_at.desc()).all()
        
        # Get all collections and tags for sidebar - filtered by current user
        collections = Collection.query.filter_by(user_id=g.user.id).all()
        tags = Tag.query.all()
        
        return render_template(
            "stashes.html",
            stashes=[s.to_dict() for s in stashes],
            collections=collections,
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
        
        if stash is None:
            logger.warning(f"Stash not found: {stash_id}")
            flash("Stash not found.", "error")
            return redirect(url_for("main.view_stashes"))
        
        return render_template("viewstash.html", stash=stash.to_dict())
    except Exception as e:
        logger.error(f"Error loading stash {stash_id}: {str(e)}")
        flash("An error occurred while loading the stash.", "error")
        return redirect(url_for("main.view_stashes"))


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
                stash.text = form.text.data
                stash.preview = stash.text[:50] + ('...' if len(stash.text) > 50 else '')
                
                # Update collection
                if form.collection.data and form.collection.data != -1:
                    stash.collection_id = form.collection.data
                else:
                    stash.collection_id = None
                
                # Update tags
                for tag in stash.tags.all():
                    stash.tags.remove(tag)
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
        
        form.text.data = stash.text
        form.collection.data = stash.collection_id or -1
        form.tags.data = ', '.join([tag.name for tag in stash.tags.all()])
        
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
        collections = Collection.query.filter_by(user_id=g.user.id).all()
        return render_template("collections.html", collections=[c.to_dict() for c in collections])
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
        tags = (
            Tag.query.join(Tag.stashes)
            .filter(Stash.user_id == g.user.id)
            .distinct()
            .all()
        )
        return render_template("tags.html", tags=[t.to_dict() for t in tags])
    except Exception as e:
        logger.error(f"Error loading tags: {str(e)}")
        flash("An error occurred while loading tags.", "error")
        return redirect(url_for("main.index"))


@bp.route("/tags/<int:tag_id>/delete", methods=["POST"])
@login_required
def delete_tag(tag_id):
    """Delete a tag."""
    try:
        tag = Tag.query.get(tag_id)
        
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
            if tag.stashes.count() == 0:
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
        data = request.get_json()
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
        data = request.get_json()
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
