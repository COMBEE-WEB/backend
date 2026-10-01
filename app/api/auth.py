import base64
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.dependencies import get_gateway, get_token
from app.schemas.auth import LoginRequest, RefreshRequest, SignupRequest
from app.schemas.auth import EmailRequest, NewPasswordRequest, ChangePasswordRequest
from app.schemas.auth import RecoveryCodeRequest

router = APIRouter(prefix='/auth', tags=['auth'])


async def require_recovery(token, gateway):
    # Verify the exact JWT remotely BEFORE inspecting its signed claims.
    user = await gateway.request('GET', '/auth/v1/user', token=token)
    try:
        payload = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        # Supabase verifyGet/verifyPost use OTP for implicit email links;
        # PKCE uses the more specific recovery authentication method.
        # Both represent recent verified possession; password sessions do not.
        recent = any(item.get('method') in ('recovery', 'otp') and
                     0 <= time.time() - float(item.get('timestamp', 0)) <= 900
                     for item in claims.get('amr', []))
        if claims.get('sub') != user['id'] or not recent:
            raise ValueError('Not a recent recovery session')
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise HTTPException(403, '재설정 링크가 유효하지 않거나 만료되었습니다. 새 메일을 요청해주세요.') from None
    return user


@router.post('/forgot-password')
async def forgot_password(payload: EmailRequest, gateway=Depends(get_gateway)):
    await gateway.request('POST', '/auth/v1/recover', body={'email': payload.email},
                          params={'redirect_to': gateway.settings.password_reset_url})
    return {'message': '가입된 이메일이라면 인증번호를 보내드립니다.'}


@router.post('/verify-recovery-code')
async def verify_recovery_code(payload: RecoveryCodeRequest, gateway=Depends(get_gateway)):
    data = await gateway.request('POST', '/auth/v1/verify', body={
        'type': 'recovery', 'email': payload.email,
        'token': payload.verificationCode.get_secret_value(),
    })
    if not data.get('access_token'):
        raise HTTPException(502, '인증 응답을 처리하지 못했습니다.')
    return session_response(data)


@router.post('/recovery-session')
async def recovery_session(token=Depends(get_token), gateway=Depends(get_gateway)):
    user = await require_recovery(token, gateway)
    return {'success': True, 'email': user.get('email')}


@router.post('/reset-password')
async def reset_password(payload: NewPasswordRequest, token=Depends(get_token), gateway=Depends(get_gateway)):
    await require_recovery(token, gateway)
    await gateway.request('PUT', '/auth/v1/user', token=token,
                          body={'password': payload.newPassword.get_secret_value()})
    return {'success': True}


@router.post('/change-password')
async def change_password(payload: ChangePasswordRequest, token=Depends(get_token), gateway=Depends(get_gateway)):
    current = payload.currentPassword.get_secret_value()
    new = payload.newPassword.get_secret_value()
    if current == new:
        raise HTTPException(400, '현재 비밀번호와 다른 비밀번호를 입력해주세요.')
    # Supabase validates current_password atomically with the password update.
    await gateway.request('PUT', '/auth/v1/user', token=token,
                          body={'password': new, 'current_password': current})
    return {'success': True}


def session_response(data):
    user = data.get('user') or data
    result = {'user': {'id': user.get('id'), 'email': user.get('email')}, 'session': None}
    if data.get('access_token'):
        result['session'] = {key: data.get(key) for key in (
            'access_token', 'refresh_token', 'token_type', 'expires_in', 'expires_at'
        )}
    return result


@router.post('/signup', status_code=201)
async def signup(payload: SignupRequest, gateway=Depends(get_gateway)):
    data = await gateway.request('POST', '/auth/v1/signup', body={
        'email': payload.email, 'password': payload.password.get_secret_value(),
        'data': {
            'login_id': payload.login_id,
            'full_name': payload.full_name,
            'nickname': payload.nickname or payload.login_id,
            'phone': payload.phone,
            'birth_date': payload.birth_date.isoformat() if payload.birth_date else None,
        },
    })
    result = session_response(data)
    result['email_confirmation_required'] = result['session'] is None
    return result


@router.post('/login')
async def login(payload: LoginRequest, gateway=Depends(get_gateway)):
    data = await gateway.request('POST', '/auth/v1/token', params={'grant_type': 'password'},
                                 body={'email': payload.email, 'password': payload.password.get_secret_value()})
    return session_response(data)


@router.post('/refresh')
async def refresh(payload: RefreshRequest, gateway=Depends(get_gateway)):
    data = await gateway.request('POST', '/auth/v1/token', params={'grant_type': 'refresh_token'},
                                 body={'refresh_token': payload.refresh_token.get_secret_value()})
    return session_response(data)


@router.get('/me')
async def me(token=Depends(get_token), gateway=Depends(get_gateway)):
    user = await gateway.request('GET', '/auth/v1/user', token=token)
    profiles = await gateway.request('GET', '/rest/v1/profiles', token=token,
                                     params={'id': f'eq.{user["id"]}', 'select': 'id,nickname,avatar_url,role,status', 'limit': '1'})
    private = await gateway.request('GET', '/rest/v1/member_private', token=token,
                                    params={'user_id': f'eq.{user["id"]}', 'select': 'login_id,full_name,phone,birth_date', 'limit': '1'})
    return {'user': {'id': user['id'], 'email': user.get('email')},
            'profile': profiles[0] if profiles else None,
            'member': private[0] if private else None}


@router.post('/logout', status_code=204)
async def logout(token=Depends(get_token), gateway=Depends(get_gateway)):
    await gateway.request('POST', '/auth/v1/logout', token=token, params={'scope': 'local'})
    return Response(status_code=204)
