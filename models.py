"""
Database models for the Ruff application.
"""

import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from uuid import uuid4
from flask_sqlalchemy import SQLAlchemy

from utils import compose_sheet, roster_items, sheet_preview, sheet_title, time_ago, utcnow

db = SQLAlchemy()


class User(db.Model):
    """Model for user accounts."""
    
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True, index=True)
    email = db.Column(db.String(120), nullable=False, unique=True, index=True)
    # Unused since sign-in became passwordless (email links); kept for old rows
    password_hash = db.Column(db.String(255), nullable=True)
    # Single-use secret in the current sign-in link (rotated on request and use)
    login_nonce = db.Column(db.String(64), nullable=True)
    # Bumped by "sign out everywhere"; sessions carry a fingerprint of it
    session_epoch = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    email_verified_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    
    # Relationships
    stashes = db.relationship('Stash', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self) -> str:
        """String representation of User."""
        return f'<User {self.username}>'
    
    def to_dict(self) -> dict:
        """Convert user to dictionary."""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'stash_count': len(self.stashes),
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        }


# Association table for many-to-many relationship between Stash and Tag
stash_tags = db.Table(
    'stash_tags',
    db.Column('stash_id', db.String(36), db.ForeignKey('stashes.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id'), primary_key=True)
)


class Tag(db.Model):
    """Model for tagging stashes."""
    
    __tablename__ = 'tags'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    
    # Relationship to stashes (many-to-many)
    stashes = db.relationship(
        'Stash',
        secondary=stash_tags,
        backref=db.backref('tags', lazy='selectin'),
        lazy='selectin'
    )
    
    def __repr__(self) -> str:
        """String representation of Tag."""
        return f'<Tag {self.name}>'
    
    def to_dict(self) -> dict:
        """Convert tag to dictionary."""
        return {
            'id': self.id,
            'name': self.name,
            'stash_count': len(self.stashes),
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        }


class Stash(db.Model):
    """
    A stash: one plain-text sheet. `body` is the source of truth; `title`
    (first line), `preview` and `checklist` (Recess Roster lines) are derived
    from it by set_text() and kept as columns for listing, search and export.
    """
    
    __tablename__ = 'stashes'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200))
    body = db.Column(db.Text, nullable=False)
    checklist = db.Column(db.Text)
    preview = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    # Server time of the last write: the cursor for syncing devices
    synced_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (db.Index("ix_stashes_user_synced", "user_id", "synced_at"),)

    def __init__(self, body: str, title: Optional[str] = None, checklist=None, **kwargs) -> None:
        """Create from sheet text, or from old-style title/body/checklist parts."""
        super().__init__(**kwargs)
        self.set_text(compose_sheet(body, title, checklist))

    def set_text(self, text: str) -> None:
        """Replace the sheet text and refresh everything derived from it."""
        self.body = (text or "").replace("\r\n", "\n")
        self.title = sheet_title(self.body)
        self.preview = sheet_preview(self.body)
        items = roster_items(self.body)
        self.checklist = json.dumps(items) if items else None
    
    def __repr__(self) -> str:
        """String representation of Stash."""
        return f'<Stash {self.id}>'
    

    def get_checklist(self) -> List[Dict]:
        """Return checklist items as a list of dicts."""
        if not self.checklist:
            return []
        try:
            data = json.loads(self.checklist)
        except Exception:
            return []

        if not isinstance(data, list):
            return []

        normalized = []
        for item in data:
            if isinstance(item, dict):
                text = str(item.get("text", "")).strip()
                done = bool(item.get("done", False))
            else:
                text = str(item).strip()
                done = False
            if text:
                normalized.append({"text": text, "done": done})
        return normalized

    def to_dict(self) -> dict:
        """Convert stash to dictionary."""
        return {
            'id': self.id,
            'title': self.title,
            'body': self.body,
            'checklist': self.get_checklist(),
            'preview': self.preview,
            'tags': sorted(tag.name for tag in self.tags),
            'updated_ago': time_ago(self.updated_at),
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
        }
    
    def add_tag(self, tag_input) -> None:
        """Add a tag to this stash. Can accept Tag object or string."""
        # Handle both Tag objects and string names
        if isinstance(tag_input, Tag):
            tag = tag_input
        else:
            tag_name = str(tag_input).lower()
            tag = Tag.query.filter_by(name=tag_name).first()
            if not tag:
                tag = Tag(name=tag_name)
                db.session.add(tag)
        
        if tag not in self.tags:
            self.tags.append(tag)
    
    def remove_tag(self, tag_input) -> None:
        """Remove a tag from this stash. Can accept Tag object or string."""
        # Handle both Tag objects and string names
        if isinstance(tag_input, Tag):
            tag = tag_input
        else:
            tag_name = str(tag_input).lower()
            tag = Tag.query.filter_by(name=tag_name).first()
        
        if tag and tag in self.tags:
            self.tags.remove(tag)


class RelaySession(db.Model):
    """Time-boxed relay session for collaborative stashes."""

    __tablename__ = "relay_sessions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    code = db.Column(db.String(8), nullable=False, unique=True, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    prompt = db.Column(db.Text, nullable=True)
    is_closed = db.Column(db.Boolean, nullable=False, default=False)
    max_entries = db.Column(db.Integer, nullable=False, default=8)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    closed_at = db.Column(db.DateTime, nullable=True)

    entries = db.relationship(
        "RelayEntry",
        backref="session",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="RelayEntry.position",
    )

    @staticmethod
    def expiry_cutoff(retention_days: int) -> datetime:
        """Relays created before this moment have expired."""
        return utcnow() - timedelta(days=retention_days)

    def is_expired(self, retention_days: int) -> bool:
        return self.created_at < self.expiry_cutoff(retention_days)

    @classmethod
    def purge_expired(cls, retention_days: int) -> int:
        """Delete expired relays and their entries; return how many relays went."""
        expired_ids = db.session.query(cls.id).filter(
            cls.created_at < cls.expiry_cutoff(retention_days)
        )
        # Delete entries explicitly: SQLite doesn't enforce ON DELETE CASCADE
        # unless foreign keys are switched on per connection
        RelayEntry.query.filter(RelayEntry.session_id.in_(expired_ids.scalar_subquery())).delete(
            synchronize_session=False
        )
        count = cls.query.filter(cls.created_at < cls.expiry_cutoff(retention_days)).delete(
            synchronize_session=False
        )
        db.session.commit()
        return count

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "title": self.title,
            "prompt": self.prompt,
            "is_closed": self.is_closed,
            "max_entries": self.max_entries,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "closed_at": self.closed_at.strftime("%Y-%m-%d %H:%M:%S") if self.closed_at else None,
        }


class RelayEntry(db.Model):
    """A single line added to a relay session."""

    __tablename__ = "relay_entries"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(36), db.ForeignKey("relay_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    author_name = db.Column(db.String(80), nullable=False)
    body = db.Column(db.Text, nullable=False)
    position = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "author_name": self.author_name,
            "body": self.body,
            "position": self.position,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }


class StashTombstone(db.Model):
    """A deleted stash, so the deletion reaches the user's other devices."""

    __tablename__ = "stash_tombstones"

    stash_id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    __table_args__ = (db.Index("ix_stash_tombstones_user_deleted", "user_id", "deleted_at"),)


class FoldedNote(db.Model):
    """
    A note passed by link that opens once. Encrypted in the sender's browser;
    the key lives only in the link's #fragment, so the server stores (and can
    read) nothing but ciphertext. The row is deleted when opened.
    """

    __tablename__ = "folded_notes"

    id = db.Column(db.String(32), primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ciphertext = db.Column(db.Text, nullable=False)
    iv = db.Column(db.String(32), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)

    @classmethod
    def purge_expired(cls) -> int:
        count = cls.query.filter(cls.expires_at < utcnow()).delete(synchronize_session=False)
        db.session.commit()
        return count
