import json
import unittest
import httpx
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.posts = {1: {'id': 1, 'board': 'free', 'title': 'existing', 'content': 'hello', 'author_id': 'other'}}
        self.comments = {}
        self.calls = []
        def handler(request):
            self.calls.append(request)
            path, method, params = request.url.path, request.method, request.url.params
            if path == '/auth/v1/user':
                return httpx.Response(200, json={'id': 'owner'})
            if path == '/rest/v1/pc_builds':
                self.assertEqual(params['user_id'], 'eq.owner')
                self.assertEqual(request.headers['Authorization'], 'Bearer owner-token')
                if params['id'] != 'eq.7':
                    return httpx.Response(200, json=[])
                return httpx.Response(200, json=[{'id': 7, 'description': json.dumps({
                    'version': 1, 'request': {'programs': 'PRIVATE PROMPT'}, 'warnings': ['PRIVATE NOTE'],
                    'parts': [{'id': 10, 'name': 'CPU', 'category': 'cpu', 'quantity': 1,
                               'lowest_price': None, 'reason': 'PRIVATE REASON', 'specs': {}}], 'total_price': None})}])
            rows = self.posts if path == '/rest/v1/posts' else self.comments
            if method == 'POST':
                body = json.loads(request.content)
                new_id = max(rows.keys(), default=0) + 1
                rows[new_id] = {**body, 'id': new_id}
                return httpx.Response(201, json=[rows[new_id]])
            selected = list(rows.values())
            for key in ('id', 'author_id', 'post_id', 'board'):
                value = params.get(key, '')
                if value.startswith('eq.'):
                    selected = [row for row in selected if str(row.get(key)) == value[3:]]
            if method in ('PATCH', 'DELETE'):
                self.assertEqual(params.get('author_id'), 'eq.owner')
                for row in selected:
                    if method == 'PATCH': row.update(json.loads(request.content))
                    else: rows.pop(row['id'])
                return httpx.Response(204)
            return httpx.Response(200, json=selected)
        self.client = TestClient(create_app(Settings('https://example.supabase.co', 'public'), httpx.MockTransport(handler)))
        self.client.__enter__()
        self.headers = {'Authorization': 'Bearer owner-token'}
        self.base = '/api/community'

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_public_reads_and_authenticated_writes(self):
        self.assertEqual(self.client.get(self.base + '/posts?board=free').status_code, 200)
        self.assertEqual(self.client.get(self.base + '/posts/1').json()['content'], 'hello')
        body = {'board': 'free', 'title': 'my title', 'content': '<script>plain text</script>'}
        self.assertEqual(self.client.post(self.base + '/posts', json=body).status_code, 401)
        self.assertEqual(self.client.post(self.base + '/posts', headers=self.headers, json={**body, 'author_id': 'other'}).status_code, 422)
        self.assertEqual(self.client.post(self.base + '/posts', headers=self.headers, json={**body, 'board': 'notice'}).status_code, 422)
        result = self.client.post(self.base + '/posts', headers=self.headers, json=body)
        self.assertEqual(result.status_code, 201)
        post = self.posts[result.json()['id']]
        self.assertEqual(post['author_id'], 'owner')
        self.assertEqual(post['content'], body['content'])

    def test_private_build_snapshot_is_allowlisted_and_owner_checked(self):
        body = {'board': 'build_share', 'title': 'Build', 'content': 'Feedback please', 'build_id': 999}
        self.assertEqual(self.client.post(self.base + '/posts', headers=self.headers, json=body).status_code, 403)
        body['build_id'] = 7
        result = self.client.post(self.base + '/posts', headers=self.headers, json=body)
        self.assertEqual(result.status_code, 201)
        post_id = result.json()['id']
        self.assertNotIn('PRIVATE', self.posts[post_id]['content'])
        detail = self.client.get(self.base + f'/posts/{post_id}').json()
        self.assertEqual(detail['content'], 'Feedback please')
        self.assertIsNone(detail['shared_build']['total_price'])
        self.assertFalse(any(r.method == 'PATCH' and r.url.path.endswith('/pc_builds') for r in self.calls))
        self.client.post(self.base + f'/posts/{post_id}/edit', headers=self.headers, json={'title': 'Edited', 'content': 'New text'})
        detail = self.client.get(self.base + f'/posts/{post_id}').json()
        self.assertEqual(detail['shared_build']['parts'][0]['id'], 10)
        self.assertEqual(detail['content'], 'New text')

    def test_post_and_comment_mutations_enforce_owner(self):
        self.assertEqual(self.client.post(self.base + '/posts/1/delete', headers=self.headers, json={}).status_code, 403)
        self.assertEqual(self.client.post(self.base + '/posts/1/edit', headers=self.headers, json={'title': 'x', 'content': 'x'}).status_code, 403)
        result = self.client.post(self.base + '/posts/1/comments', headers=self.headers, json={'content': 'comment'})
        self.assertEqual(result.status_code, 201)
        comment_id = result.json()['id']
        self.assertEqual(self.comments[comment_id]['author_id'], 'owner')
        self.assertEqual(self.client.post(self.base + f'/comments/{comment_id}/edit', headers=self.headers, json={'content': 'edited'}).status_code, 200)
        self.assertEqual(self.comments[comment_id]['content'], 'edited')
        self.comments[99] = {'id': 99, 'author_id': 'other', 'post_id': 1, 'content': 'other'}
        self.assertEqual(self.client.post(self.base + '/comments/99/delete', headers=self.headers, json={}).status_code, 403)
        self.assertEqual(self.client.post(self.base + f'/comments/{comment_id}/delete', headers=self.headers, json={}).status_code, 200)
        self.assertNotIn(comment_id, self.comments)
        self.assertEqual(self.client.post(self.base + '/posts/999/comments', headers=self.headers, json={'content': 'x'}).status_code, 404)

    def test_invalid_board_and_missing_shared_build_rejected(self):
        self.assertEqual(self.client.get(self.base + '/posts?board=notice').status_code, 422)
        self.assertEqual(self.client.get(self.base + '/posts?offset=-1').status_code, 422)
        self.assertEqual(self.client.post(self.base + '/posts', headers=self.headers, json={'board': 'build_share', 'title': 'x', 'content': 'x'}).status_code, 422)


if __name__ == '__main__': unittest.main()
