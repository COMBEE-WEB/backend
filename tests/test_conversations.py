import json
import unittest
import httpx
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app

class ConversationTests(unittest.TestCase):
 def test_owner_scoped_history_favorite_update_and_delete(self):
  stored = {}
  def handler(request):
   if request.url.path == '/auth/v1/user':
    return httpx.Response(200, json={'id': 'owner'})
   self.assertEqual(request.headers['Authorization'], 'Bearer user-token')
   if request.method == 'POST':
    body = json.loads(request.content)
    self.assertEqual(body['user_id'], 'owner')
    self.assertFalse(body['is_public'])
    stored.update(json.loads(body['description']))
    return httpx.Response(201, json=[{'id': 12}])
   self.assertEqual(request.url.params['user_id'], 'eq.owner')
   self.assertEqual(request.url.params['name'], 'like.combee_chat:*')
   if request.url.params.get('id') == 'eq.99':
    return httpx.Response(200, json=[])
   if request.method == 'GET':
    return httpx.Response(200, json=[{'id': 12, 'description': json.dumps(stored), 'created_at': '2026-10-02T00:00:00Z'}])
   if request.method == 'PATCH':
    stored.update(json.loads(json.loads(request.content)['description']))
   return httpx.Response(200, json=[{'id': 12}])
  app = create_app(Settings('https://example.supabase.co', 'public'), httpx.MockTransport(handler))
  with TestClient(app) as client:
   headers = {'Authorization': 'Bearer user-token'}
   messages = [{'role': 'user', 'content': 'hello'}, {'role': 'assistant', 'content': 'hi'}]
   self.assertEqual(client.post('/api/conversations', json={'messages': messages}).status_code, 401)
   self.assertEqual(client.post('/api/conversations', headers=headers, json={'messages': messages}).json()['id'], 12)
   self.assertEqual(client.get('/api/conversations/99', headers=headers).status_code, 404)
   self.assertEqual(client.post('/api/conversations/99', headers=headers, json={'favorite': True}).status_code, 404)
   self.assertEqual(client.delete('/api/conversations/99', headers=headers).status_code, 404)
   self.assertTrue(client.post('/api/conversations/12', headers=headers, json={'favorite': True}).json()['favorite'])
   self.assertTrue(client.post('/api/conversations/12', headers=headers, json={'messages': messages}).json()['favorite'])
   self.assertEqual(len(client.get('/api/conversations', headers=headers).json()['items']), 1)
   self.assertEqual(client.delete('/api/conversations/12', headers=headers).status_code, 200)
