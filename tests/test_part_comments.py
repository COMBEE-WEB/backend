import unittest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings
from app.api.dependencies import get_gateway

class PartCommentsTests(unittest.TestCase):
 def setUp(self):
  self.gateway = AsyncMock()
  self.app = create_app(Settings('https://example.supabase.co', 'public'))
  self.app.dependency_overrides[get_gateway] = lambda: self.gateway
  self.client = TestClient(self.app)
  self.headers = {'Authorization': 'Bearer user-token'}
 def test_public_read_scoped_to_part(self):
  self.gateway.request.return_value = [{'id': i} for i in range(21)]
  response = self.client.get('/api/community/parts/7/comments')
  self.assertEqual(len(response.json()['items']), 20)
  self.assertTrue(response.json()['has_more'])
  self.assertEqual(self.gateway.request.call_args.kwargs['params']['part_id'], 'eq.7')
 def test_requires_login(self):
  self.assertEqual(self.client.post('/api/community/parts/7/comments', json={'content':'hello'}).status_code, 401)
  self.gateway.request.assert_not_called()
 def test_author_comes_from_session(self):
  self.gateway.request.side_effect = [{'id':'owner'}, [{'id':7}], [{'id':3}]]
  response = self.client.post('/api/community/parts/7/comments', headers=self.headers, json={'content':' hello '})
  self.assertEqual(response.status_code, 201)
  call = self.gateway.request.call_args
  self.assertEqual(call.kwargs['body'], {'part_id':7,'author_id':'owner','content':'hello'})
  self.assertEqual(call.kwargs['token'], 'user-token')
 def test_cannot_delete_other_author(self):
  self.gateway.request.side_effect = [{'id':'owner'}, [{'id':3,'author_id':'other'}]]
  self.assertEqual(self.client.post('/api/community/part-comments/3/delete', headers=self.headers).status_code, 403)
  self.assertEqual(self.gateway.request.call_count, 2)
 def test_missing_part(self):
  self.gateway.request.side_effect = [{'id':'owner'}, []]
  self.assertEqual(self.client.post('/api/community/parts/7/comments', headers=self.headers, json={'content':'hello'}).status_code, 404)
 def test_blank_and_spoofed_author_rejected(self):
  for body in [{'content':'  '},{'content':'hello','author_id':'other'}]:
   self.assertEqual(self.client.post('/api/community/parts/7/comments', headers=self.headers, json=body).status_code, 422)
