from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


def get_gateway(request: Request):
    return request.app.state.supabase


def get_token(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials is None:
        raise HTTPException(401, '로그인이 필요합니다.', headers={'WWW-Authenticate': 'Bearer'})
    return credentials.credentials
