
import unittest
from app import create_app
from models import db, User, Stash, Collection
from flask import g

class BulkActionsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        
        # Create a test user
        self.user = User(username='testuser', email='test@example.com')
        self.user.set_password('password')
        db.session.add(self.user)
        db.session.commit()
        
        # Create another user
        self.other_user = User(username='other', email='other@example.com')
        self.other_user.set_password('password')
        db.session.add(self.other_user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def login(self, client, username, password):
        return client.post('/login', data=dict(
            username=username,
            password=password
        ), follow_redirects=True)

    def test_bulk_delete(self):
        client = self.app.test_client()
        self.login(client, 'testuser', 'password')
        
        # Create stashes
        s1 = Stash(text="Stash 1", user_id=self.user.id)
        s2 = Stash(text="Stash 2", user_id=self.user.id)
        s3 = Stash(text="Stash 3", user_id=self.other_user.id) # Should not be deleted
        db.session.add_all([s1, s2, s3])
        db.session.commit()
        
        # Mock g.user for the route logic if needed, but client.post handles session
        # However, the route uses g.user, which is set by @login_required -> load_logged_in_user
        
        response = client.post('/stash/bulk/delete', json={
            'stash_ids': [s1.id, s2.id, s3.id]
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['deleted'], 2) # Should only delete 2
        
        self.assertIsNone(Stash.query.get(s1.id))
        self.assertIsNone(Stash.query.get(s2.id))
        self.assertIsNotNone(Stash.query.get(s3.id))

    def test_bulk_move(self):
        client = self.app.test_client()
        self.login(client, 'testuser', 'password')
        
        # Create stashes and collection
        c1 = Collection(name="My Collection", user_id=self.user.id)
        db.session.add(c1)
        db.session.commit()
        
        s1 = Stash(text="Stash 1", user_id=self.user.id)
        s2 = Stash(text="Stash 2", user_id=self.user.id)
        db.session.add_all([s1, s2])
        db.session.commit()
        
        response = client.post('/stash/bulk/move', json={
            'stash_ids': [s1.id, s2.id],
            'collection_id': c1.id
        })
        
        self.assertEqual(response.status_code, 200)
        
        # Refresh objects
        db.session.refresh(s1)
        db.session.refresh(s2)
        
        self.assertEqual(s1.collection_id, c1.id)
        self.assertEqual(s2.collection_id, c1.id)

if __name__ == '__main__':
    unittest.main()
