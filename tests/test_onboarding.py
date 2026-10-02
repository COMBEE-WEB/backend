import json
import unittest
import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.api.onboarding import CATALOG, KEY, assessment


class OnboardingTests(unittest.TestCase):
    def correct(self, level):
        return [q[2] for q in CATALOG['quizzes'][level]]

    def wrong(self, level):
        return [(q[2] + 1) % 3 for q in CATALOG['quizzes'][level]]

    def test_threshold_and_downgrade(self):
        answers = self.correct('intermediate')
        answers[3:] = self.wrong('intermediate')[3:]
        self.assertEqual(assessment('intermediate', {'intermediate': answers})['scores']['intermediate'], 6)
        self.assertEqual(assessment('intermediate', {'intermediate': answers})['level'], 'intermediate')
        answers[2] = self.wrong('intermediate')[2]
        self.assertEqual(assessment('intermediate', {'intermediate': answers})['level'], 'beginner')
        first = assessment('advanced', {'advanced': self.wrong('advanced')})
        self.assertFalse(first['completed'])
        self.assertEqual(first['next_level'], 'intermediate')
        self.assertEqual(assessment('advanced', {'advanced': self.wrong('advanced'), 'intermediate': self.correct('intermediate')})['level'], 'intermediate')
        self.assertEqual(assessment('advanced', {'advanced': self.wrong('advanced'), 'intermediate': self.wrong('intermediate')})['level'], 'beginner')
        self.assertEqual(assessment('advanced', {'advanced': self.correct('advanced')})['level'], 'advanced')
        self.assertEqual(assessment('beginner', {})['level'], 'beginner')

    def test_no_skipping_or_invalid_answers(self):
        for claimed, attempts in [('advanced', {'intermediate': self.correct('intermediate')}),
                                   ('beginner', {'advanced': []}), ('intermediate', {'intermediate': [0]}),
                                   ('intermediate', {'intermediate': [True] * 5}),
                                   ('intermediate', {'intermediate': [-1] * 5})]:
            with self.assertRaises(HTTPException):
                assessment(claimed, attempts)

    def test_account_persistence_questions_and_preference_handoff(self):
        metadata = {'nickname': 'keep-me'}
        writes = []
        def handler(request):
            self.assertEqual(request.url.path, '/auth/v1/user')
            self.assertEqual(request.headers['Authorization'], 'Bearer owner-token')
            if request.method == 'PUT':
                payload = json.loads(request.content)
                self.assertEqual(set(payload), {'data'})
                metadata.update(payload['data'])
                writes.append(payload)
            return httpx.Response(200, json={'id': 'owner', 'user_metadata': metadata})
        app = create_app(Settings('https://example.supabase.co', 'public'), httpx.MockTransport(handler))
        with TestClient(app) as client:
            root = '/api/estimates/onboarding'
            headers = {'Authorization': 'Bearer owner-token'}
            self.assertEqual(client.get(root).status_code, 401)
            catalog = client.get(root, headers=headers).json()
            self.assertIsNone(catalog['profile'])
            self.assertEqual(set(catalog['quizzes']['advanced'][0]), {'question', 'options'})
            diagnosis = client.post(root, headers=headers, json={'claimed_level': 'advanced', 'attempts': {'advanced': self.wrong('advanced')}})
            self.assertFalse(diagnosis.json()['completed'])
            self.assertEqual(len(writes), 0)
            client.post(root, headers=headers, json={'claimed_level': 'advanced', 'attempts': {'advanced': self.wrong('advanced'), 'intermediate': self.correct('intermediate')}})
            self.assertEqual(metadata[KEY]['level'], 'intermediate')
            body = {'answers': [0]*5, 'budget_won': 1500000, 'purpose': '게임', 'programs': 'PUBG', 'owned': ''}
            response = client.post(root + '/preferences', headers=headers, json=body)
            self.assertEqual(response.status_code, 200)
            saved = client.get(root, headers=headers).json()['profile']
            self.assertEqual(saved['preferences']['conditions']['budget_won'], 1500000)
            self.assertIn('CPU', saved['preferences']['conditions']['preferences'])
            self.assertEqual(metadata['nickname'], 'keep-me')
            client.post(root, headers=headers, json={'claimed_level': 'beginner', 'attempts': {}})
            beginner_questions = client.get(root, headers=headers).json()['surveys']['beginner']
            self.assertEqual(len(beginner_questions), 6)
            body['answers'] = [0] * len(beginner_questions)
            self.assertEqual(client.post(root + '/preferences', headers=headers, json=body).status_code, 200)
            saved = client.get(root, headers=headers).json()['profile']['preferences']['conditions']
            self.assertEqual(saved['budget_won'], 1500000)
            self.assertEqual(saved['purpose'], '게임')
            self.assertEqual(saved['programs'], 'PUBG')
            self.assertIn('외관', saved['preferences'])
            body['answers'] = [5]*5
            self.assertEqual(client.post(root + '/preferences', headers=headers, json=body).status_code, 422)
            client.post(root, headers=headers, json={'claimed_level': 'advanced', 'attempts': {'advanced': self.correct('advanced')}})
            body.update(answers=[], keywords=['invented-tag'])
            self.assertEqual(client.post(root + '/preferences', headers=headers, json=body).status_code, 422)
            body['keywords'] = [next(iter(CATALOG['keywords'].values()))[0]]
            self.assertEqual(client.post(root + '/preferences', headers=headers, json=body).status_code, 200)


if __name__ == '__main__':
    unittest.main()
