"""
Export/Import utilities for Ruff stashes.
"""

import json
from uuid import uuid4
from datetime import datetime
from typing import Dict, List, Any, Optional
from models import db, User, Stash, Collection, Tag


def export_user_data(user: User) -> Dict[str, Any]:
    """
    Export all user data (stashes, collections, tags) as a dictionary.
    
    Args:
        user: User object to export
        
    Returns:
        Dictionary with exported data
    """
    export_data = {
        'version': '1.0',
        'exported_at': datetime.utcnow().isoformat(),
        'user': {
            'username': user.username,
            'email': user.email,
        },
        'collections': [],
        'stashes': [],
        'tags': [],
    }
    
    # Export collections
    for collection in user.collections:
        export_data['collections'].append({
            'id': collection.id,
            'name': collection.name,
            'description': collection.description,
            'created_at': collection.created_at.isoformat(),
        })
    
    # Export tags used by this user's stashes
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
    
    # Export stashes
    for stash in user.stashes:
        stash_data = {
            'id': stash.id,
            'title': stash.title,
            'body': stash.body,
            'checklist': stash.get_checklist(),
            'preview': stash.preview,
            'collection_id': stash.collection_id,
            'collection_name': stash.collection.name if stash.collection else None,
            'tags': [tag.name for tag in stash.tags],
            'created_at': stash.created_at.isoformat(),
            'updated_at': stash.updated_at.isoformat(),
        }
        export_data['stashes'].append(stash_data)
    
    return export_data


def export_to_json(user: User) -> str:
    """Export user data as JSON string."""
    export_data = export_user_data(user)
    return json.dumps(export_data, indent=2)


def export_stash_to_text(stash: Stash) -> str:
    """Export a single stash as formatted text."""
    title = stash.title or stash.preview
    text = f"# {title}\n\n"
    text += f"**Created:** {stash.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
    text += f"**Updated:** {stash.updated_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
    
    if stash.collection:
        text += f"**Collection:** {stash.collection.name}\n"
    
    if len(stash.tags) > 0:
        tags = [tag.name for tag in stash.tags]
        text += f"**Tags:** {', '.join(tags)}\n"

    checklist_items = stash.get_checklist()
    if checklist_items:
        text += "**Checklist:**\n"
        for item in checklist_items:
            mark = "x" if item.get("done") else " "
            text += f"- [{mark}] {item.get('text')}\n"
    
    text += f"\n---\n\n{stash.body}"
    return text


def import_from_json(user: User, json_data: str) -> Dict[str, Any]:
    """
    Import stashes, collections, and tags from JSON.
    
    Args:
        user: User to import data for
        json_data: JSON string with exported data
        
    Returns:
        Dictionary with import results
    """
    def _parse_datetime(value: Any) -> Optional[datetime]:
        """Best-effort ISO8601 parser that returns None on failure."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    try:
        data = json.loads(json_data)
    except json.JSONDecodeError as e:
        return {
            'success': False,
            'error': f'Invalid JSON: {str(e)}',
            'created': {'collections': 0, 'stashes': 0, 'tags': 0},
        }
    
    results = {
        'success': True,
        'error': None,
        'created': {'collections': 0, 'stashes': 0, 'tags': 0},
        'skipped': {'collections': 0, 'stashes': 0, 'tags': 0},
    }
    
    try:
        # Import collections
        collection_map = {}  # Map old IDs to new IDs
        for col_data in data.get('collections', []):
            existing = Collection.query.filter_by(
                user_id=user.id,
                name=col_data['name']
            ).first()
            
            if existing:
                collection_map[col_data['id']] = existing.id
                results['skipped']['collections'] += 1
            else:
                new_col = Collection(
                    user_id=user.id,
                    name=col_data['name'],
                    description=col_data.get('description'),
                )
                db.session.add(new_col)
                db.session.flush()
                collection_map[col_data['id']] = new_col.id
                results['created']['collections'] += 1
        
        # Import tags
        tag_map = {}  # Map tag names to tag objects
        for tag_data in data.get('tags', []):
            existing = Tag.query.filter_by(name=tag_data['name']).first()
            
            if existing:
                tag_map[tag_data['name']] = existing
                results['skipped']['tags'] += 1
            else:
                new_tag = Tag(name=tag_data['name'])
                db.session.add(new_tag)
                db.session.flush()
                tag_map[tag_data['name']] = new_tag
                results['created']['tags'] += 1
        
        # Import stashes
        for stash_data in data.get('stashes', []):
            # If this user already has the stash ID, skip
            existing_same_user = Stash.query.filter_by(
                user_id=user.id,
                id=stash_data['id']
            ).first()
            if existing_same_user:
                results['skipped']['stashes'] += 1
                continue

            # If the ID exists globally for another user, mint a new one
            existing_any = db.session.get(Stash, stash_data['id'])
            stash_id = stash_data['id'] if existing_any is None else str(uuid4())

            # Map collection ID
            collection_id = None
            if stash_data.get('collection_id'):
                collection_id = collection_map.get(stash_data['collection_id'])
            elif stash_data.get('collection_name'):
                col = Collection.query.filter_by(
                    user_id=user.id,
                    name=stash_data['collection_name']
                ).first()
                if col:
                    collection_id = col.id
            
            checklist_items = stash_data.get('checklist')
            if not isinstance(checklist_items, list):
                checklist_items = []

            new_stash = Stash(
                id=stash_id,
                user_id=user.id,
                title=stash_data.get('title'),
                body=stash_data.get('body') or stash_data.get('text') or "",
                checklist=checklist_items,
                collection_id=collection_id,
            )
            db.session.add(new_stash)
            db.session.flush()
            
            # Restore timestamps when present (parse strings to datetime)
            created_at = _parse_datetime(stash_data.get('created_at'))
            updated_at = _parse_datetime(stash_data.get('updated_at'))
            if created_at:
                new_stash.created_at = created_at
            if updated_at:
                new_stash.updated_at = updated_at
            
            # Add tags
            for tag_name in stash_data.get('tags', []):
                tag = tag_map.get(tag_name)
                if tag:
                    new_stash.tags.append(tag)
            
            results['created']['stashes'] += 1
        
        db.session.commit()
        return results
    
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': f'Import failed: {str(e)}',
            'created': {'collections': 0, 'stashes': 0, 'tags': 0},
        }
