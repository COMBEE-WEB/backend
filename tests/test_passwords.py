import base64
import json
import time
import unittest

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def token(method='recovery', age=0, subject='user-id'):
    payload = json.dumps({'sub': subject, 'amr': [{'method': method, 'timestamp': time.time() - age}]}).encode()
    return 'header.' + base64.urlsafe_b64encode(payload).decode().rstrip('=') + '.signature'


class PasswordTests(unittest.TestCase):
    def client(self, handler):
        return TestClient(create_app(Settings('https://example.supabase.co', 'test'), httpx.MockTransport(handler)))

    def test_code_verification_is_bound_to_email_and_recovery(self):
        def handler(request):
            self.assertEqual(request.url.path, '/auth/v1/verify')
            self.assertEqual(json.loads(request.content), {
                'type': 'recovery', 'email': 'test@example.com', 'token': '012345',
            })
            return httpx.Response(200, json={'access_token': token('otp'), 'refresh_token': 'refresh',
                                           'expires_in': 3600, 'user': {'id': 'user-id', 'email': 'test@example.com'}})
        with self.client(handler) as client:
            result = client.post('/api/auth/verify-recovery-code', json={
                'email': 'test@example.com', 'verificationCode': '012345', 'type': 'signup',
            })
            self.assertEqual(result.status_code, 200)
            self.assertTrue(result.json()['session']['access_token'])

    def test_wrong_or_expired_code_does_not_return_session(self):
        with self.client(lambda r: httpx.Response(403, json={'error_code': 'otp_expired'})) as client:
            result = client.post('/api/auth/verify-recovery-code', json={'email': 'test@example.com', 'verificationCode': '123456'})
            self.assertEqual(result.status_code, 403)
            self.assertNotIn('session', result.json())
            self.assertNotIn('123456', result.text)

    def test_invalid_code_format_is_not_forwarded(self):
        with self.client(lambda r: self.fail('Invalid code sent upstream')) as client:
            for code in ['12345', '123456789', 'abcdef', '１２３４５６']:
                result = client.post('/api/auth/verify-recovery-code', json={'email': 'test@example.com', 'verificationCode': code})
                self.assertEqual(result.status_code, 422)
                self.assertNotIn(code, result.text)

    def test_eight_digit_code_preserves_leading_zero(self):
        def handler(request):
            self.assertEqual(json.loads(request.content)['token'], '01234567')
            return httpx.Response(200, json={'access_token': token('otp'), 'user': {'id': 'user-id'}})
        with self.client(handler) as client:
            result = client.post('/api/auth/verify-recovery-code', json={
                'email': 'test@example.com', 'verificationCode': '01234567',
            })
            self.assertEqual(result.status_code, 200)

    def test_forgot_password_uses_fixed_redirect(self):
        def handler(request):
            self.assertEqual(request.url.path, '/auth/v1/recover')
            self.assertEqual(request.url.params['redirect_to'], 'http://localhost:3000/auth/reset-password')
            self.assertEqual(json.loads(request.content), {'email': 'test@example.com'})
            return httpx.Response(200, json={})
        with self.client(handler) as client:
            response = client.post('/api/auth/forgot-password', json={'email': 'test@example.com', 'redirect_to': 'https://evil.invalid'})
            self.assertEqual(response.status_code, 200)

    def test_recovery_must_be_verified_upstream(self):
        with self.client(lambda r: httpx.Response(401, json={})) as client:
            response = client.post('/api/auth/recovery-session', headers={'Authorization': f'Bearer {token()}'})
            self.assertEqual(response.status_code, 401)

    def test_implicit_email_link_uses_otp_amr(self):
        # Matches Supabase verify.go: implicit recovery calls issueRefreshToken(..., models.OTP).
        with self.client(lambda r: httpx.Response(200, json={'id': 'user-id', 'email': 'test@example.com'})) as client:
            response = client.post('/api/auth/recovery-session', headers={'Authorization': f'Bearer {token("otp")}'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['email'], 'test@example.com')

    def test_forged_otp_still_requires_supabase_verification(self):
        with self.client(lambda r: httpx.Response(401, json={})) as client:
            response = client.post('/api/auth/recovery-session', headers={'Authorization': f'Bearer {token("otp")}'})
            self.assertEqual(response.status_code, 401)

    def test_reset_rejects_normal_expired_and_mismatched_sessions(self):
        def handler(request):
            self.assertEqual(request.method, 'GET')
            return httpx.Response(200, json={'id': 'user-id'})
        with self.client(handler) as client:
            for value in [token('password'), token(age=901), token('otp', age=901), token('otp', subject='other'), token(subject='other'), 'malformed']:
                response = client.post('/api/auth/reset-password', json={'newPassword': 'newPassword123'}, headers={'Authorization': f'Bearer {value}'})
                self.assertEqual(response.status_code, 403)

    def test_valid_recovery_updates_password_after_verification(self):
        methods = []
        def handler(request):
            methods.append(request.method)
            if request.method == 'GET':
                return httpx.Response(200, json={'id': 'user-id'})
            self.assertEqual(json.loads(request.content), {'password': 'newPassword123'})
            return httpx.Response(200, json={'id': 'user-id'})
        with self.client(handler) as client:
            response = client.post('/api/auth/reset-password', json={'newPassword': 'newPassword123'}, headers={'Authorization': f'Bearer {token()}'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(methods, ['GET', 'PUT'])
            self.assertNotIn('newPassword123', response.text)

    def test_change_sends_current_password_for_verification(self):
        def handler(request):
            self.assertEqual(request.method, 'PUT')
            self.assertEqual(request.headers['Authorization'], 'Bearer session')
            self.assertEqual(json.loads(request.content), {'password': 'newPassword123', 'current_password': 'oldPassword123'})
            return httpx.Response(422, json={'error_code': 'invalid_credentials'})
        with self.client(handler) as client:
            response = client.post('/api/auth/change-password', json={'currentPassword': 'oldPassword123', 'newPassword': 'newPassword123'}, headers={'Authorization': 'Bearer session'})
            self.assertEqual(response.status_code, 422)

    def test_missing_auth_short_and_same_password(self):
        with self.client(lambda r: self.fail('Unexpected upstream call')) as client:
            self.assertEqual(client.post('/api/auth/reset-password', json={'newPassword': 'password123'}).status_code, 401)
            for new, expected in [('short', 422), ('password123', 400)]:
                response = client.post('/api/auth/change-password', json={'currentPassword': 'password123', 'newPassword': new}, headers={'Authorization': 'Bearer token'})
                self.assertEqual(response.status_code, expected)
                self.assertNotIn('password123', response.text)


if __name__ == '__main__':
    unittest.main()
