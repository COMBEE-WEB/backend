import httpx
from fastapi import HTTPException

from app.config import Settings


class SupabaseGateway:
    """Stateless requests: never share a user's session between requests."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    async def request(self, method, path, *, token=None, body=None, params=None, prefer=None):
        if not self.settings.supabase_url or not self.settings.supabase_key:
            raise HTTPException(503, 'Supabase 연결 설정이 필요합니다.')
        headers = {'apikey': self.settings.supabase_key}
        if prefer:
            headers['Prefer'] = prefer
        if token:
            headers['Authorization'] = f'Bearer {token}'
        try:
            response = await self.client.request(
                method, f'{self.settings.supabase_url}{path}',
                headers=headers, json=body, params=params,
            )
        except httpx.TimeoutException:
            raise HTTPException(504, 'Supabase 응답 시간이 초과되었습니다.') from None
        except httpx.RequestError:
            raise HTTPException(502, 'Supabase에 연결할 수 없습니다.') from None
        if response.is_error:
            # Do not expose upstream SQL errors, user data, or credentials.
            status = response.status_code
            messages = {
                400: '요청 정보를 확인해주세요.',
                401: '인증 정보가 올바르지 않거나 만료되었습니다.',
                403: '접근 권한이 없습니다.',
                404: '요청한 정보를 찾을 수 없습니다.',
                409: '이미 사용 중인 정보입니다.',
                422: '입력값 또는 계정 상태를 확인해주세요.',
                429: '요청이 많습니다. 잠시 후 다시 시도해주세요.',
            }
            if status == 429 and path == '/auth/v1/recover':
                raise HTTPException(429, 'Supabase가 재설정 메일 요청을 일시적으로 제한했습니다. 반복 요청을 멈추고 나중에 다시 시도해주세요. 기본 메일 제공자는 프로젝트 전체 시간당 2통, 같은 사용자 재요청은 기본 60초 간격으로 제한됩니다.')
            if status in (400, 403) and path == '/auth/v1/verify':
                raise HTTPException(status, '인증번호가 올바르지 않거나 만료되었습니다. 이메일과 최신 인증번호를 확인해주세요.')
            raise HTTPException(status if status in messages else 502,
                                messages.get(status, 'Supabase 요청을 처리하지 못했습니다.'))
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            raise HTTPException(502, 'Supabase 응답 형식이 올바르지 않습니다.') from None
