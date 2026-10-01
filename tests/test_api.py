import unittest

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

SETTINGS = Settings('https://example.supabase.co', 'sb_publishable_test')


class ApiTests(unittest.TestCase):
    def client(self, handler, settings=SETTINGS):
        return TestClient(create_app(settings, httpx.MockTransport(handler)))

    def test_missing_config_and_health(self):
        with self.client(lambda r: None, Settings('', '')) as client:
            self.assertEqual(client.get('/health').json(), {'status': 'ok'})
            self.assertEqual(client.get('/api/parts').status_code, 503)

    def test_signup_metadata_and_confirmation(self):
        import json

        def handler(request):
            self.assertEqual(request.url.path, '/auth/v1/signup')
            body = json.loads(request.content)
            self.assertEqual(body['data']['login_id'], 'tester')
            self.assertEqual(body['data']['birth_date'], '2000-01-02')
            self.assertNotIn('Authorization', request.headers)
            return httpx.Response(200, json={'id': 'user-id', 'email': body['email']})

        with self.client(handler) as client:
            response = client.post('/api/auth/signup', json={
                'userId': 'tester', 'email': 'test@example.com', 'password': 'password123',
                'name': '테스트', 'birthDate': '20000102',
            })
            self.assertEqual(response.status_code, 201)
            self.assertTrue(response.json()['email_confirmation_required'])
            self.assertIsNone(response.json()['session'])
            self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_invalid_password_not_echoed(self):
        with self.client(lambda r: None) as client:
            response = client.post('/api/auth/signup', json={
                'userId': 'tester', 'email': 'test@example.com', 'password': 'secret', 'name': 'Test',
            })
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('secret', response.text)

    def test_me_requires_token(self):
        with self.client(lambda r: self.fail('Unexpected upstream request')) as client:
            self.assertEqual(client.get('/api/auth/me').status_code, 401)
            self.assertEqual(client.post('/api/auth/logout').status_code, 401)

    def test_me_verifies_token_and_keeps_user_rls(self):
        paths = []

        def handler(request):
            paths.append(request.url.path)
            self.assertEqual(request.headers['Authorization'], 'Bearer user-token')
            self.assertEqual(request.headers['apikey'], SETTINGS.supabase_key)
            if request.url.path == '/auth/v1/user':
                return httpx.Response(200, json={'id': 'verified-id', 'email': 'test@example.com'})
            self.assertIn('eq.verified-id', str(request.url))
            return httpx.Response(200, json=[{'nickname': 'tester'}])

        with self.client(handler) as client:
            response = client.get('/api/auth/me', headers={'Authorization': 'Bearer user-token'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(paths[0], '/auth/v1/user')
            self.assertEqual(len(paths), 3)

    def test_expired_token_stops_profile_queries(self):
        def handler(request):
            self.assertEqual(request.url.path, '/auth/v1/user')
            return httpx.Response(401, json={'message': 'sensitive upstream error'})

        with self.client(handler) as client:
            response = client.get('/api/auth/me', headers={'Authorization': 'Bearer expired'})
            self.assertEqual(response.status_code, 401)
            self.assertNotIn('sensitive', response.text)

    def test_login_and_refresh_session(self):
        def handler(request):
            self.assertEqual(request.url.path, '/auth/v1/token')
            self.assertIn(request.url.params['grant_type'], ['password', 'refresh_token'])
            return httpx.Response(200, json={
                'access_token': 'access', 'refresh_token': 'refresh',
                'token_type': 'bearer', 'expires_in': 3600, 'user': {'id': 'user-id'},
            })

        with self.client(handler) as client:
            for path, body in [('login', {'email': 'test@example.com', 'password': 'password123'}),
                               ('refresh', {'refresh_token': 'old-refresh'})]:
                response = client.post(f'/api/auth/{path}', json=body)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['session']['access_token'], 'access')

    def test_logout_empty_response(self):
        def handler(request):
            self.assertEqual(request.url.params['scope'], 'local')
            return httpx.Response(204)

        with self.client(handler) as client:
            self.assertEqual(client.post('/api/auth/logout', headers={
                'Authorization': 'Bearer token',
            }).status_code, 204)

    def test_parts_filters_and_not_found(self):
        def handler(request):
            self.assertEqual(request.url.params['is_active'], 'eq.true')
            self.assertNotIn('Authorization', request.headers)
            return httpx.Response(200, json=[])

        with self.client(handler) as client:
            self.assertEqual(client.get('/api/parts?limit=101').status_code, 422)
            self.assertEqual(client.get('/api/parts?category=cpu').json()['items'], [])
            self.assertEqual(client.get('/api/parts/1').status_code, 404)

    def test_timeout(self):
        def handler(request):
            raise httpx.ReadTimeout('timeout', request=request)

        with self.client(handler) as client:
            self.assertEqual(client.get('/api/parts').status_code, 504)

    def test_parts_search_pagination_and_literal_filters(self):
        def handler(request):
            params = request.url.params
            self.assertEqual(params['limit'], '3')
            self.assertEqual(params['offset'], '2')
            self.assertEqual(params['name'], 'ilike.%Ryzen%')
            self.assertEqual(params['manufacturer'], 'ilike.amd')
            return httpx.Response(200, json=[{'id': 3}, {'id': 4}, {'id': 5}])
        with self.client(handler) as client:
            response = client.get('/api/parts', params={'category': 'cpu', 'q': ' Ryzen ', 'manufacturer': 'amd', 'limit': 2, 'offset': 2})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['items'], [{'id': 3}, {'id': 4}])
            self.assertTrue(response.json()['has_more'])

    def test_parts_invalid_category_and_empty_page(self):
        with self.client(lambda r: httpx.Response(200, json=[])) as client:
            self.assertEqual(client.get('/api/parts?category=invalid').status_code, 422)
            self.assertEqual(client.get('/api/parts?offset=-1').status_code, 422)
            self.assertFalse(client.get('/api/parts?q=missing').json()['has_more'])


if __name__ == '__main__':
    unittest.main()
