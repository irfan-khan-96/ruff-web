"""
Export/Import utilities for Ruff stashes.
"""

import json
import logging
from uuid import uuid4
from datetime import datetime
from typing import Dict, List, Any, Optional
from flask import current_app

from models import db, User, Stash, Tag
from utils import utcnow

logger = logging.getLogger(__name__)

# Column limits (titles: stashes.title, tags: tags.name)
MAX_TITLE_LENGTH = 200
MAX_TAG_LENGTH = 50


def export_user_data(user: User) -> Dict[str, Any]:
    """
    Everything a user has stashed, as a dictionary (export format version 2).

    `body` is the full sheet text; `title` and `checklist` are derived from it
    and included so other tools (and version 1 importers) can read them.
    """
    export_data = {
        'version': '2.0',
        'exported_at': utcnow().isoformat(),
        'user': {
            'username': user.username,
            'email': user.email,
        },
        'stashes': [],
        'tags': [],
    }

    user_tags = (
        Tag.query.join(Tag.stashes)
        .filter(Stash.user_id == user.id)
        .distinct()
        .all()
    )
    for tag in user_tags:
        export_data['tags'].append({
            'id': tag.id,
            'name': tag.name,
            'created_at': tag.created_at.isoformat(),
        })

    for stash in user.stashes:
        export_data['stashes'].append({
            'id': stash.id,
            'title': stash.title,
            'body': stash.body,
            'checklist': stash.get_checklist(),
            'tags': sorted(tag.name for tag in stash.tags),
            'created_at': stash.created_at.isoformat(),
            'updated_at': stash.updated_at.isoformat(),
        })

    return export_data


def export_to_json(user: User) -> str:
    """Export user data as JSON string."""
    return json.dumps(export_user_data(user), indent=2)


def export_stash_to_text(stash: Stash) -> str:
    """A stash as plain text: the sheet itself, then its tags."""
    text = stash.body.rstrip("\n") + "\n"
    if stash.tags:
        text += "\nTags: " + ", ".join(sorted("#" + tag.name for tag in stash.tags)) + "\n"
    return text


def import_from_json(user: User, json_data: str) -> Dict[str, Any]:
    """
    Restore stashes and tags from an export (version 1 or 2).

    Version 1 files had separate title/body/checklist fields and collections;
    those become sheet text and tags. Stashes the user already has are skipped.
    """
    def _parse_datetime(value: Any) -> Optional[datetime]:
        """Best-effort ISO8601 parser that returns None on failure."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def _valid_tag(name: Any) -> bool:
        return isinstance(name, str) and 0 < len(name.strip().lower()) <= MAX_TAG_LENGTH

    empty = {'stashes': 0, 'tags': 0}
    try:
        data = json.loads(json_data)
    except json.JSONDecodeError as e:
        return {'success': False, 'error': f'Invalid JSON: {str(e)}', 'created': dict(empty)}

    results = {
        'success': True,
        'error': None,
        'created': dict(empty),
        'skipped': {'stashes': 0, 'tags': 0, 'too_large': 0},
    }
    max_body = current_app.config["MAX_STASH_LENGTH"]
    known_tags = {tag.name for tag in Tag.query.all()}

    try:
        # Version 1 collections: remembered by id so their stashes get a tag
        collection_names = {
            col.get('id'): col.get('name')
            for col in data.get('collections', []) if isinstance(col, dict)
        }

        for stash_data in data.get('stashes', []):
            body = stash_data.get('body') or stash_data.get('text') or ""
            title = stash_data.get('title')
            checklist = stash_data.get('checklist') if isinstance(stash_data.get('checklist'), list) else []
            if len(str(body)) > max_body or (title and len(str(title)) > MAX_TITLE_LENGTH):
                results['skipped']['too_large'] += 1
                continue

            # If this user already has the stash ID, skip
            if Stash.query.filter_by(user_id=user.id, id=stash_data['id']).first():
                results['skipped']['stashes'] += 1
                continue

            # If the ID exists globally for another user, mint a new one
            stash_id = stash_data['id'] if db.session.get(Stash, stash_data['id']) is None else str(uuid4())

            new_stash = Stash(id=stash_id, user_id=user.id, title=title, body=str(body), checklist=checklist)
            db.session.add(new_stash)
            db.session.flush()

            created_at = _parse_datetime(stash_data.get('created_at'))
            updated_at = _parse_datetime(stash_data.get('updated_at'))
            if created_at:
                new_stash.created_at = created_at
            if updated_at:
                new_stash.updated_at = updated_at

            tag_names = list(stash_data.get('tags') or [])
            collection = stash_data.get('collection_name') or collection_names.get(stash_data.get('collection_id'))
            if collection:
                tag_names.append(collection)
            for name in tag_names:
                if not _valid_tag(name):
                    results['skipped']['tags'] += 1
                    continue
                name = name.strip().lower()
                if name not in known_tags:
                    known_tags.add(name)
                    results['created']['tags'] += 1
                new_stash.add_tag(name)

            results['created']['stashes'] += 1

        db.session.commit()
        return results

    except Exception as e:
        db.session.rollback()
        # Log the details; show the user a generic message (no DB internals)
        logger.error(f"Import failed for user {user.id}: {e}")
        return {
            'success': False,
            'error': "That doesn't look like a backup from here.",
            'created': dict(empty),
        }
