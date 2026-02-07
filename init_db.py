"""
Database initialization and migration utilities.

Use this script to:
1. Initialize a fresh database
"""

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
        total_chars = sum(len(s.body) for s in Stash.query.all())
        
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
        elif command == 'clear':
            clear_database()
        elif command == 'stats':
            show_statistics()
        else:
            print("Usage:")
            print("  python init_db.py init          - Initialize database")
            print("  python init_db.py stats         - Show database statistics")
            print("  python init_db.py clear         - Clear all data (WARNING!)")
    else:
        print("Database Utilities")
        print("-" * 50)
        init_database()
        show_statistics()
