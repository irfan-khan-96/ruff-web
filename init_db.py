"""
Database initialization and migration utilities.

Use this script to:
1. Initialize a fresh database
2. Migrate data from session storage to database
"""

import os
import json
import uuid
from datetime import datetime
from flask import session
from app import create_app
from models import db, Stash


def init_database():
    """Initialize a fresh database."""
    app = create_app()
    
    with app.app_context():
        # Create all tables
        db.create_all()
        print("✓ Database initialized successfully!")
        print(f"✓ Database location: {app.config['SQLALCHEMY_DATABASE_URI']}")


def migrate_session_to_database(session_file: str = None):
    """
    Migrate stashes from Flask session to database.
    
    Args:
        session_file: Path to session file (optional, for advanced migration)
    """
    app = create_app()
    
    with app.app_context():
        # Create tables if they don't exist
        db.create_all()
        
        if session_file and os.path.exists(session_file):
            # Advanced migration from session file
            try:
                with open(session_file, 'r') as f:
                    session_data = json.load(f)
                    stashes = session_data.get('stashes', [])
                    
                    for stash_data in stashes:
                        # Create stash if it doesn't already exist
                        existing = Stash.query.get(stash_data.get('id'))
                        if not existing:
                            stash = Stash(
                                id=stash_data.get('id', str(uuid.uuid4())),
                                text=stash_data.get('text', ''),
                                preview=stash_data.get('preview', '')
                            )
                            db.session.add(stash)
                    
                    db.session.commit()
                    print(f"✓ Migrated {len(stashes)} stashes from session file!")
            except Exception as e:
                print(f"✗ Migration failed: {str(e)}")
                db.session.rollback()
        else:
            print("✓ No session file to migrate. Starting with fresh database.")


def clear_database():
    """Clear all data from database (WARNING: This cannot be undone!)."""
    app = create_app()
    
    with app.app_context():
        response = input("⚠️  This will delete ALL stashes! Type 'yes' to confirm: ")
        if response.lower() == 'yes':
            db.drop_all()
            db.create_all()
            print("✓ Database cleared!")
        else:
            print("✗ Cancelled.")


def show_statistics():
    """Display database statistics."""
    app = create_app()
    
    with app.app_context():
        stash_count = Stash.query.count()
        total_chars = sum(len(s.text) for s in Stash.query.all())
        
        print("\n" + "="*50)
        print("DATABASE STATISTICS")
        print("="*50)
        print(f"Total Stashes: {stash_count}")
        print(f"Total Characters: {total_chars:,}")
        if stash_count > 0:
            print(f"Average Size: {total_chars // stash_count:,} characters")
        print("="*50 + "\n")


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == 'init':
            init_database()
        elif command == 'migrate':
            session_file = sys.argv[2] if len(sys.argv) > 2 else None
            migrate_session_to_database(session_file)
        elif command == 'clear':
            clear_database()
        elif command == 'stats':
            show_statistics()
        else:
            print("Usage:")
            print("  python init_db.py init          - Initialize database")
            print("  python init_db.py migrate       - Migrate from session")
            print("  python init_db.py stats         - Show database statistics")
            print("  python init_db.py clear         - Clear all data (WARNING!)")
    else:
        print("Database Utilities")
        print("-" * 50)
        init_database()
        show_statistics()
