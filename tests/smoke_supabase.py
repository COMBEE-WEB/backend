"""Read-only live check. Run explicitly; excluded from unittest discovery."""
from fastapi.testclient import TestClient

from app.main import app


def main():
    with TestClient(app) as client:
        response = client.get('/api/parts?limit=1')
        if response.status_code != 200:
            raise SystemExit(f'Parts connection failed: HTTP {response.status_code}')
        data = response.json()
        if not isinstance(data.get('items'), list):
            raise SystemExit('Unexpected parts response')
        print('FastAPI -> Supabase parts: OK')
        if data['items']:
            detail = client.get(f'/api/parts/{data["items"][0]["id"]}')
            if detail.status_code != 200:
                raise SystemExit(f'Part detail failed: HTTP {detail.status_code}')
            print('FastAPI -> Supabase part detail: OK')
        else:
            print('No public active parts; detail check skipped')


if __name__ == '__main__':
    main()
