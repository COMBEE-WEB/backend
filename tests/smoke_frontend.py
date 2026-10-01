"""Opt-in real login test using the ignored .env.signup-test file. No signup."""
import os
from pathlib import Path

import httpx
from dotenv import dotenv_values


def main():
    credentials = dotenv_values(Path(__file__).resolve().parents[1] / '.env.signup-test')
    origin = os.getenv('FRONTEND_URL', 'http://127.0.0.1:3000')
    with httpx.Client(base_url=origin, timeout=30) as client:
        rejected = client.post('/api/auth/login', headers={'Origin': 'https://untrusted.invalid'}, json={})
        assert rejected.status_code == 403, 'Cross-origin write was not rejected'
        assert client.get('/api/auth/me').status_code == 401
        client.headers['Origin'] = origin
        invalid = client.post('/api/auth/login', json={'email': 'invalid', 'password': ''})
        assert invalid.status_code == 422
        response = client.post('/api/auth/login', json={
            'email': credentials['TEST_EMAIL'], 'password': credentials['TEST_PASSWORD'],
        })
        assert response.status_code == 200, f'Login failed: {response.status_code}'
        assert 'access_token' not in response.text and 'refresh_token' not in response.text
        assert all('httponly' in value.lower() for value in response.headers.get_list('set-cookie'))
        assert client.cookies.get('combee_refresh')
        print('Login / HttpOnly cookies / token redaction / CSRF: OK')
        try:
            account = client.get('/api/auth/me')
            assert account.status_code == 200
            assert account.json()['member']['login_id'] == credentials['TEST_LOGIN_ID']
            assert account.json()['profile']['nickname'] == credentials['TEST_LOGIN_ID']
            print('Auth user / profile / member trigger: OK')
            for cookie in list(client.cookies.jar):
                if cookie.name == 'combee_access':
                    client.cookies.delete(cookie.name, domain=cookie.domain, path=cookie.path)
            renewed = client.get('/api/auth/me')
            assert renewed.status_code == 200, f'Refresh failed: {renewed.status_code}'
            assert client.cookies.get('combee_access')
            print('Automatic session refresh: OK')
        finally:
            logout = client.post('/api/auth/logout')
            assert logout.status_code == 200
        assert client.get('/api/auth/me').status_code == 401
        assert not client.cookies.get('combee_access') and not client.cookies.get('combee_refresh')
        print('Logout / cookie cleanup / unauthenticated access: OK')


if __name__ == '__main__':
    main()
