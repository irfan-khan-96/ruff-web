#!/usr/bin/env python
"""
Comprehensive feature test for Ruff app
Tests all CRUD operations for Stashes, Collections, and Tags
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from models import db, Stash, Collection, Tag

def test_collections():
    print("\n=== Testing Collections ===")
    app = create_app('development')
    
    with app.app_context():
        # Create collections
        col1 = Collection(name="Work", description="Work-related stashes")
        col2 = Collection(name="Personal", description="Personal notes")
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

def test_tags():
    print("\n=== Testing Tags ===")
    app = create_app('development')
    
    with app.app_context():
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

def test_stashes():
    print("\n=== Testing Stashes ===")
    app = create_app('development')
    
    with app.app_context():
        # Create collection and tags
        col = Collection(name="Test", description="Test collection")
        tag1 = Tag(name="test-tag-1")
        tag2 = Tag(name="test-tag-2")
        db.session.add_all([col, tag1, tag2])
        db.session.commit()
        
        # Create stashes
        long_text = "This is my first stash with some important content " * 5  # Make it long
        stash1 = Stash(
            text=long_text,
            collection_id=col.id
        )
        stash1.add_tag(tag1)
        stash1.add_tag(tag2)
        
        stash2 = Stash(
            text="Another stash with different information",
            collection_id=col.id
        )
        stash2.add_tag(tag1)
        
        db.session.add_all([stash1, stash2])
        db.session.commit()
        print(f"✓ Created 2 stashes with tags")
        
        # Verify relationships
        assert stash1.tags.count() == 2
        assert stash2.tags.count() == 1
        print(f"✓ Stash 1 has {stash1.tags.count()} tags")
        print(f"✓ Stash 2 has {stash2.tags.count()} tags")
        
        # Verify preview
        assert len(stash1.preview) > 0
        assert stash1.preview != stash1.text  # Should be truncated
        print(f"✓ Preview generated: '{stash1.preview}'")
        
        # Verify timestamps
        assert stash1.created_at is not None
        assert stash1.updated_at is not None
        print(f"✓ Created at: {stash1.created_at}")
        
        # Test editing
        stash1.text = "Updated content here"
        stash1.update_preview()  # Update preview after text change
        db.session.commit()
        assert stash1.preview == "Updated content here"
        print(f"✓ Stash updated successfully")
        
        # Test deletion
        db.session.delete(stash1)
        db.session.commit()
        assert Stash.query.count() == 1
        print(f"✓ Stash deleted, remaining: {Stash.query.count()}")

def test_relationships():
    print("\n=== Testing Relationships ===")
    app = create_app('development')
    
    with app.app_context():
        # Create test data with unique names
        col = Collection(name="Main-Rel")
        tag = Tag(name="rel-important")
        stash = Stash(text="Test stash")
        
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
        assert tag in stash.tags.all()
        assert stash in tag.stashes.all()
        print(f"✓ Tag relationship works (many-to-many)")
        
        # Test cascade
        col2 = Collection.query.filter_by(name="Main-Rel").first()
        stashes_in_col = Stash.query.filter_by(collection_id=col2.id).all()
        print(f"✓ Stashes in collection: {len(stashes_in_col)}")

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
