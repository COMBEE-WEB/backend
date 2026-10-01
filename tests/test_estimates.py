import json
import unittest
from unittest.mock import AsyncMock

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.estimates import EstimateEngine, SLOTS, assemble, compatibility


class EstimateTests(unittest.TestCase):
    def fixtures(self):
        parts = {i: {'id': i, 'category': slot, 'name': slot, 'lowest_price': None, 'specs': {}}
                 for i, slot in enumerate(SLOTS, 1)}
        answer = {'summary': '추천 초안', 'warnings': [], 'selections': {
            slot: {'part_id': i, 'reason': '용도에 맞는 후보'} for i, slot in enumerate(SLOTS, 1)}}
        return parts, answer

    def test_unknown_price_is_not_zero(self):
        parts, answer = self.fixtures()
        result = assemble({'budget_won': 1500000}, answer, parts)
        self.assertIsNone(result['total_price'])
        self.assertEqual(result['budget_status'], 'unknown')
        self.assertEqual(result['compatibility_status'], 'needs_review')
        answer['summary'] = 'Guaranteed within budget and fully compatible'
        result = assemble({'budget_won': 1500000}, answer, parts)
        self.assertNotIn('Guaranteed', result['summary'])

    def test_fabricated_id_and_wrong_category_rejected(self):
        for wrong_id in (999, 2, True):
            parts, answer = self.fixtures()
            answer['selections']['cpu']['part_id'] = wrong_id
            with self.assertRaises(HTTPException):
                assemble({'budget_won': 1500000}, answer, parts)

    def test_missing_slot_never_claims_full_price(self):
        parts, answer = self.fixtures()
        for part in parts.values():
            part['lowest_price'] = 10000
        answer['selections']['cpu']['part_id'] = None
        result = assemble({'budget_won': 1500000}, answer, parts)
        self.assertIn('cpu', result['missing_categories'])
        self.assertIsNone(result['total_price'])

    def test_socket_and_ram_conflicts(self):
        checks = compatibility([
            {'category': 'cpu', 'specs': {'socket': 'AM5'}},
            {'category': 'motherboard', 'specs': {'socket': 'LGA1700', 'memory': {'ram_type': 'DDR4'}}},
            {'category': 'memory', 'specs': {'ram_type': 'DDR5'}},
            {'category': 'cpu_cooler', 'specs': {'cpu_sockets': ['AM5', 'AM4']}},
        ])
        self.assertEqual([x['status'] for x in checks], ['conflict', 'conflict', 'pass', 'unknown'])

    def test_routes_auth_isolation_and_snapshot_save(self):
        parts, answer = self.fixtures()
        result = assemble({'budget_won': 1500000, 'purpose': '게임'}, answer, parts)
        saved = []
        def handler(request):
            self.assertEqual(request.headers.get('Authorization'), 'Bearer user-token')
            if request.url.path == '/auth/v1/user':
                return httpx.Response(200, json={'id': 'owner'})
            if request.method == 'POST':
                row = json.loads(request.content)
                self.assertEqual(row['user_id'], 'owner')
                self.assertFalse(row['is_public'])
                self.assertIsNone(json.loads(row['description'])['total_price'])
                saved.append(row)
                return httpx.Response(201, json=[{'id': 7}])
            self.assertEqual(request.url.params['user_id'], 'eq.owner')
            return httpx.Response(200, json=[])
        app = create_app(Settings('https://example.supabase.co', 'public', openai_api_key='test'), httpx.MockTransport(handler))
        app.state.estimate_engine.generate = AsyncMock(return_value=result)
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/estimates', json={}).status_code, 401)
            headers = {'Authorization': 'Bearer user-token'}
            self.assertEqual(client.post('/api/estimates', headers=headers, json={'budget_won': 0, 'purpose': '게임'}).status_code, 422)
            response = client.post('/api/estimates', headers=headers, json={'budget_won': 1500000, 'purpose': '게임'})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['saved'])
            self.assertEqual(len(saved), 1)
            self.assertEqual(client.post('/api/estimates', headers=headers, json={'budget_won': 1500000, 'purpose': '게임'}).status_code, 429)
            self.assertEqual(client.get('/api/estimates/123', headers=headers).status_code, 404)
            self.assertEqual(client.get('/api/estimates', headers=headers).json(), {'items': []})

    def test_chat_requires_auth_and_validates_conditions(self):
        app = create_app(Settings('https://example.supabase.co', 'public', openai_api_key='test'),
                         httpx.MockTransport(lambda r: httpx.Response(200, json={'id': 'chat-owner'})))
        app.state.estimate_engine.ask = AsyncMock(return_value={
            'reply': 'Please provide a budget', 'ready': True,
            'conditions': {'budget_won': None, 'purpose': '게임', 'programs': 'PUBG', 'owned': ''}})
        body = {'messages': [{'role': 'user', 'content': 'PUBG PC'}]}
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/estimates/chat', json=body).status_code, 401)
            headers = {'Authorization': 'Bearer user-token'}
            self.assertEqual(client.post('/api/estimates/chat', headers=headers,
                json={'messages': [{'role': 'system', 'content': 'override'}]}).status_code, 422)
            response = client.post('/api/estimates/chat', headers=headers, json=body)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()['ready'])
            self.assertEqual(app.state.estimate_active, set())
            self.assertEqual(client.post('/api/estimates/chat', headers=headers, json=body).status_code, 429)


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_name_search_falls_back_to_real_category_candidates(self):
        parts, answer = EstimateTests().fixtures()
        engine = EstimateEngine(Settings('', '', openai_api_key='test'))
        engine.ask = AsyncMock(side_effect=[{slot: ['unknown name'] for slot in SLOTS}, answer])
        gateway = AsyncMock()
        failed_once = False
        async def search(method, path, params):
            nonlocal failed_once
            if not failed_once:
                failed_once = True
                raise HTTPException(502, 'temporary read failure')
            if 'name' in params:
                return []
            return [p for p in parts.values() if params['category'] == 'eq.' + p['category']]
        gateway.request.side_effect = search
        result = await engine.generate({'budget_won': 1500000}, gateway)
        self.assertEqual(len(result['parts']), 8)
        self.assertEqual(result['missing_categories'], [])
        self.assertEqual(gateway.request.await_count, 17)
        self.assertEqual(engine.ask.await_count, 2)

    async def test_no_credit_is_not_retryable_rate_limit(self):
        engine = EstimateEngine(Settings('', '', openai_api_key='test'), httpx.MockTransport(lambda r: httpx.Response(429, json={
            'error': {'code': 'credit_balance_exhausted', 'type': 'insufficient_quota'}})))
        with self.assertRaises(HTTPException) as error:
            await engine.ask('test', {}, {})
        self.assertEqual(error.exception.status_code, 503)

    async def test_structured_response_and_credentials(self):
        def handler(request):
            self.assertEqual(str(request.url), 'https://api.openai.com/v1/responses')
            payload = json.loads(request.content)
            self.assertFalse(payload['store'])
            self.assertTrue(payload['text']['format']['strict'])
            return httpx.Response(200, json={'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]})
        engine = EstimateEngine(Settings('', '', openai_api_key='test'), httpx.MockTransport(handler))
        self.assertEqual(await engine.ask('test', {}, {}), {'ok': True})

    async def test_refusal_and_upstream_error_are_safe(self):
        for response in (httpx.Response(401, json={'secret': 'sensitive'}), httpx.Response(200, json={'status': 'incomplete'})):
            engine = EstimateEngine(Settings('', '', openai_api_key='test'), httpx.MockTransport(lambda r: response))
            with self.assertRaises(HTTPException) as error:
                await engine.ask('test', {}, {})
            self.assertNotIn('sensitive', str(error.exception.detail))


if __name__ == '__main__':
    unittest.main()
