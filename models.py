"""
Database models for the Ruff application.
"""

from datetime import datetime
import json
from typing import Optional, List, Dict
from uuid import uuid4
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

from utils import generate_stash_preview

db = SQLAlchemy()


class User(db.Model):
    """Model for user accounts."""
    
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True, index=True)
    email = db.Column(db.String(120), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    email_verified_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    stashes = db.relationship('Stash', backref='user', lazy=True, cascade='all, delete-orphan')
    collections = db.relationship('Collection', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self) -> str:
        """String representation of User."""
        return f'<User {self.username}>'
    
    def set_password(self, password: str) -> None:
        """Hash and set the user password."""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password: str) -> bool:
        """Verify the user password."""
        return check_password_hash(self.password_hash, password)
    
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


class Collection(db.Model):
    """Model for organizing stashes into collections."""
    
    __tablename__ = 'collections'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationship to stashes
    stashes = db.relationship('Stash', backref='collection', lazy=True)
    
    __table_args__ = (db.UniqueConstraint('user_id', 'name', name='uq_user_collection_name'),)
    
    def __repr__(self) -> str:
        """String representation of Collection."""
        return f'<Collection {self.name}>'
    
    def to_dict(self) -> dict:
        """Convert collection to dictionary."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'stash_count': len(self.stashes),
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        }


class Tag(db.Model):
    """Model for tagging stashes."""
    
    __tablename__ = 'tags'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
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
    """Model for storing stashes with titles, body, and checklist."""
    
    __tablename__ = 'stashes'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200))
    body = db.Column(db.Text, nullable=False)
    checklist = db.Column(db.Text)
    preview = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Foreign key for collection (optional)
    collection_id = db.Column(db.Integer, db.ForeignKey('collections.id'), nullable=True)
    
    def __init__(self, body: str, title: Optional[str] = None, checklist=None, **kwargs) -> None:
        """Initialize Stash with auto-generated preview."""
        super().__init__(**kwargs)
        self.title = title.strip() if isinstance(title, str) and title.strip() else None
        self.body = body
        if checklist is not None:
            self.set_checklist(checklist)
        if not getattr(self, "preview", None):
            self.preview = generate_stash_preview(self.body)
    
    def __repr__(self) -> str:
        """String representation of Stash."""
        return f'<Stash {self.id}>'
    
    def update_preview(self) -> None:
        """Update preview based on current text."""
        self.preview = generate_stash_preview(self.body)

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

    def set_checklist(self, items) -> None:
        """Persist checklist items as JSON."""
        normalized = []
        for item in items or []:
            if isinstance(item, dict):
                text = str(item.get("text", "")).strip()
                done = bool(item.get("done", False))
            else:
                text = str(item).strip()
                done = False
            if text:
                normalized.append({"text": text, "done": done})
        self.checklist = json.dumps(normalized) if normalized else None
    
    def to_dict(self) -> dict:
        """Convert stash to dictionary."""
        return {
            'id': self.id,
            'title': self.title,
            'body': self.body,
            'checklist': self.get_checklist(),
            'preview': self.preview,
            'collection_id': self.collection_id,
            'collection_name': self.collection.name if self.collection else None,
            'tags': [tag.name for tag in self.tags],
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
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    prompt = db.Column(db.Text, nullable=True)
    is_closed = db.Column(db.Boolean, nullable=False, default=False)
    max_entries = db.Column(db.Integer, nullable=False, default=8)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    closed_at = db.Column(db.DateTime, nullable=True)

    entries = db.relationship(
        "RelayEntry",
        backref="session",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="RelayEntry.position",
    )

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
    session_id = db.Column(db.String(36), db.ForeignKey("relay_sessions.id"), nullable=False, index=True)
    author_name = db.Column(db.String(80), nullable=False)
    body = db.Column(db.Text, nullable=False)
    position = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "author_name": self.author_name,
            "body": self.body,
            "position": self.position,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
