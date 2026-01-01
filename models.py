"""
Database models for the Ruff application.
"""

from datetime import datetime
from uuid import uuid4
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    """Model for user accounts."""
    
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True, index=True)
    email = db.Column(db.String(120), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
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
        backref=db.backref('tags', lazy='dynamic'),
        lazy='dynamic'
    )
    
    def __repr__(self) -> str:
        """String representation of Tag."""
        return f'<Tag {self.name}>'
    
    def to_dict(self) -> dict:
        """Convert tag to dictionary."""
        return {
            'id': self.id,
            'name': self.name,
            'stash_count': self.stashes.count(),
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        }


class Stash(db.Model):
    """Model for storing text stashes."""
    
    __tablename__ = 'stashes'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    preview = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Foreign key for collection (optional)
    collection_id = db.Column(db.Integer, db.ForeignKey('collections.id'), nullable=True)
    
    def __init__(self, text: str, **kwargs) -> None:
        """Initialize Stash with auto-generated preview."""
        super().__init__(**kwargs)
        self.text = text
        # Generate preview from text (first 100 chars or until newline)
        preview_length = 100
        preview = text[:preview_length]
        if len(text) > preview_length:
            preview += '...'
        self.preview = preview
    
    def __repr__(self) -> str:
        """String representation of Stash."""
        return f'<Stash {self.id}>'
    
    def _generate_preview(self) -> str:
        """Generate preview from text."""
        preview_length = 100
        preview = self.text[:preview_length]
        if len(self.text) > preview_length:
            preview += '...'
        return preview
    
    def update_preview(self) -> None:
        """Update preview based on current text."""
        self.preview = self._generate_preview()
    
    def to_dict(self) -> dict:
        """Convert stash to dictionary."""
        return {
            'id': self.id,
            'text': self.text,
            'preview': self.preview,
            'collection_id': self.collection_id,
            'collection_name': self.collection.name if self.collection else None,
            'tags': [tag.name for tag in self.tags.all()],
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

