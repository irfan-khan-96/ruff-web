#!/usr/bin/env python
"""
Comprehensive feature test for Ruff app
Tests all CRUD operations for Stashes, Collections, and Tags
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from models import db, Stash, Collection, Tag, User

def test_collections():
    print("\n=== Testing Collections ===")
    app = create_app('testing')
    
    with app.app_context():
        db.create_all()
        user = User(username="tester", email="tester@example.com")
        user.set_password("password")
        db.session.add(user)
        db.session.commit()
        # Create collections
        col1 = Collection(user_id=user.id, name="Work", description="Work-related stashes")
        col2 = Collection(user_id=user.id, name="Personal", description="Personal notes")
        db.session.add(col1)
        db.session.add(col2)
        db.session.commit()
        print(f"✓ Created 2 collections")
        
        # Verify
        collections = Collection.query.all()
        assert len(collections) == 2
        print(f"✓ Retrieved {len(collections)} collections")
        
        # Test deletion
        db.session.delete(col1)
        db.session.commit()
        assert Collection.query.count() == 1
        print(f"✓ Deleted collection, remaining: {Collection.query.count()}")
        db.session.remove()
        db.drop_all()

def test_tags():
    print("\n=== Testing Tags ===")
    app = create_app('testing')
    
    with app.app_context():
        db.create_all()
        user = User(username="tester", email="tester@example.com")
        user.set_password("password")
        db.session.add(user)
        db.session.commit()
        # Create tags
        tag1 = Tag(name="important")
        tag2 = Tag(name="urgent")
        db.session.add_all([tag1, tag2])
        db.session.commit()
        print(f"✓ Created 2 tags")
        
        # Verify
        tags = Tag.query.all()
        assert len(tags) == 2
        print(f"✓ Retrieved {len(tags)} tags")
        db.session.remove()
        db.drop_all()

def test_stashes():
    print("\n=== Testing Stashes ===")
    app = create_app('testing')
    
    with app.app_context():
        db.create_all()
        user = User(username="tester", email="tester@example.com")
        user.set_password("password")
        db.session.add(user)
        db.session.commit()
        # Create collection and tags
        col = Collection(user_id=user.id, name="Test", description="Test collection")
        tag1 = Tag(name="test-tag-1")
        tag2 = Tag(name="test-tag-2")
        db.session.add_all([col, tag1, tag2])
        db.session.commit()
        
        # Create stashes
        long_text = "This is my first stash with some important content " * 5  # Make it long
        stash1 = Stash(
            body=long_text,
            title="First stash",
            checklist=[{"text": "Ship v1", "done": False}],
            collection_id=col.id,
            user_id=user.id
        )
        stash1.add_tag(tag1)
        stash1.add_tag(tag2)
        
        stash2 = Stash(
            body="Another stash with different information",
            collection_id=col.id,
            user_id=user.id
        )
        stash2.add_tag(tag1)
        
        db.session.add_all([stash1, stash2])
        db.session.commit()
        print(f"✓ Created 2 stashes with tags")

        # Verify checklist
        assert len(stash1.get_checklist()) == 1
        print("✓ Checklist stored")
        
        # Verify relationships
        assert len(stash1.tags) == 2
        assert len(stash2.tags) == 1
        print(f"✓ Stash 1 has {len(stash1.tags)} tags")
        print(f"✓ Stash 2 has {len(stash2.tags)} tags")
        
        # Verify preview
        assert len(stash1.preview) > 0
        assert stash1.preview != stash1.body  # Should be truncated
        print(f"✓ Preview generated: '{stash1.preview}'")
        
        # Verify timestamps
        assert stash1.created_at is not None
        assert stash1.updated_at is not None
        print(f"✓ Created at: {stash1.created_at}")
        
        # Test editing
        stash1.body = "Updated content here"
        stash1.update_preview()  # Update preview after text change
        db.session.commit()
        assert stash1.preview == "Updated content here"
        print(f"✓ Stash updated successfully")
        
        # Test deletion
        db.session.delete(stash1)
        db.session.commit()
        assert Stash.query.count() == 1
        print(f"✓ Stash deleted, remaining: {Stash.query.count()}")
        db.session.remove()
        db.drop_all()

def test_relationships():
    print("\n=== Testing Relationships ===")
    app = create_app('testing')
    
    with app.app_context():
        db.create_all()
        user = User(username="tester", email="tester@example.com")
        user.set_password("password")
        db.session.add(user)
        db.session.commit()
        # Create test data with unique names
        col = Collection(user_id=user.id, name="Main-Rel")
        tag = Tag(name="rel-important")
        stash = Stash(body="Test stash", user_id=user.id)
        
        db.session.add_all([col, tag, stash])
        db.session.commit()
        
        # Test collection relationship
        stash.collection = col
        db.session.commit()
        assert stash.collection.name == "Main-Rel"
        print(f"✓ Collection relationship works")
        
        # Test tag relationship
        stash.add_tag(tag)
        db.session.commit()
        assert tag in stash.tags
        assert stash in tag.stashes
        print(f"✓ Tag relationship works (many-to-many)")
        
        # Test cascade
        col2 = Collection.query.filter_by(name="Main-Rel").first()
        stashes_in_col = Stash.query.filter_by(collection_id=col2.id).all()
        print(f"✓ Stashes in collection: {len(stashes_in_col)}")
        db.session.remove()
        db.drop_all()

if __name__ == "__main__":
    try:
        test_collections()
        test_tags()
        test_stashes()
        test_relationships()
        
        print("\n" + "="*50)
        print("✅ ALL TESTS PASSED!")
        print("="*50)
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
