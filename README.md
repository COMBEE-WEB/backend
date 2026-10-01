# COMBEE backend

FastAPI + 기존 Supabase Auth / Data API를 사용합니다. DB를 복원하거나 테이블을 생성하지 않습니다.

## 실행 (PowerShell, backend 폴더)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# .env의 SUPABASE_PUBLISHABLE_KEY에 대시보드의 publishable key 입력
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

이미 `.env`가 있으면 덮어쓰지 말고 필요한 항목만 추가합니다.
URL: http://localhost:8000 / API 문서: http://localhost:8000/docs

`SUPABASE_ANON_KEY`로 기존 anon 키도 지원합니다. `service_role` 또는 secret 키를 사용하지 않습니다.
사용자 조회는 Bearer 토큰을 전달하여 기존 RLS를 적용합니다. 부품은 공개 읽기 정책을 사용합니다.
`/health`는 서버 실행 여부만 확인하며, Supabase 연결 검증은 `/api/parts?limit=1`로 합니다.

## API

| 메서드 | 경로 | 기능 |
| --- | --- | --- |
| GET | /health | 서버 상태 |
| POST | /api/auth/signup | 회원가입 |
| POST | /api/auth/login | 이메일/비밀번호 로그인 |
| POST | /api/auth/refresh | 세션 갱신 |
| GET | /api/auth/me | 본인 계정·프로필·회원 정보 |
| POST | /api/auth/logout | 현재 세션 로그아웃 |
| POST | /api/auth/forgot-password | 재설정 메일 요청 (email) |
| POST | /api/auth/verify-recovery-code | 이메일 인증번호 확인 (email, verificationCode) |
| POST | /api/auth/recovery-session | 이메일 재설정 토큰 검증 |
| POST | /api/auth/reset-password | 이메일 인증 후 변경 (newPassword) |
| POST | /api/auth/change-password | 로그인 후 변경 (currentPassword, newPassword) |
| GET | /api/parts | 활성 부품 목록 (category, q, manufacturer, limit, offset) |
| GET | /api/parts/{id} | 활성 부품 상세 |

부품 목록은 `q`로 제품명을 부분 검색하고, `manufacturer`로 제조사명을 대소문자 구분 없이
일치 검색합니다. 목록 응답의 `has_more`로 다음 페이지 여부를 확인합니다.
프론트 `/Parts/partlist`에서 30개 분류를 선택할 수 있고 Next.js `/api/parts`를 통해 조회합니다.
부품 상세는 선택한 ID로 별도 조회하며 가격이 없으면 정보 없음으로 표시합니다.
데이터 가져오기·라이선스 안내는 `scripts/BUILDCORES.md`를 참고하세요.
대량 업로드 후 `supabase/migrations/20260929_parts_search_indexes.sql`을 실행해
페이지 조회 인덱스를 추가하고 PostgreSQL 통계를 갱신합니다.

회원가입은 프론트의 `userId`, `email`, `password`, `name`, `phone`, `birthDate`를 받습니다.
생일 `YYYYMMDD`를 `YYYY-MM-DD`로 변환합니다. Supabase에 전달하는 메타데이터는 백업의
`handle_new_user` 트리거가 사용하는 `login_id`, `full_name`, `nickname`, `phone`, `birth_date`입니다.
비밀번호는 Supabase Auth만 저장합니다. 앱 테이블에 별도 비밀번호를 저장하지 않습니다.

로그인 입력은 `email`, `password`입니다. 사용자 아이디 로그인은 아직 구현하지 않았습니다.
로그인·갱신 응답의 `session`에는 `access_token`, `refresh_token` 등이 들어 있습니다.
갱신 요청은 `refresh_token`을 받으며, 갱신 후 새 토큰 쌍으로 교체해야 합니다.
`/me`, `/logout`에는 `Authorization: Bearer <access_token>`이 필요합니다.
로그아웃 후 클라이언트도 세션을 삭제해야 합니다. 이미 발급된 access token은 만료까지 유효할 수 있습니다.

이메일 확인이 활성화되어 있으면 가입 결과는 `session: null`, `email_confirmation_required: true`입니다.
Supabase Authentication의 Site URL을 프론트 주소로 설정하고 이메일 확인 후 로그인합니다.
프론트의 회원가입·로그인·로그아웃은 Next.js `/api/auth/*` 경유로 연결되어 있습니다.
Next.js 서버가 HttpOnly 쿠키로 토큰을 보관하며 `/me` 조회 시 만료된 세션을 갱신합니다.
프론트와 백엔드를 각각 실행해야 합니다. 프론트 `BACKEND_URL` 기본값은 `http://127.0.0.1:8000`입니다.
아이디 찾기, 커뮤니티,
AI 견적, 실력 테스트 API는 후속 구현 대상입니다.

## 비밀번호 찾기·변경

찾기는 이메일 입력 → 6~8자리 인증번호 확인 → 새 비밀번호 설정 순서입니다.
Supabase Authentication → Email Templates → Reset password 본문을
`supabase/templates/recovery.html` 내용으로 설정해야 합니다. `{{ .Token }}`이 인증번호로 치환됩니다.
이 파일을 저장하는 것만으로 호스팅된 프로젝트에 반영되지는 않습니다. 대시보드 저장이 필요합니다.
인증번호 검증은 `/auth/v1/verify`에 이메일, token, `type=recovery`를 전달합니다.
성공 시 Next.js가 전용 HttpOnly 쿠키에 인증 토큰을 보관하고 프론트에는 토큰을 반환하지 않습니다.
발송 성공 후 60초 동안 재발송 버튼을 비활성화합니다. 프로젝트의 시간당 발송 제한은 별도로 적용됩니다.

기존에 발송된 링크 호환을 위한 `/auth/reset-password` 화면도 유지합니다.
`PASSWORD_RESET_URL` 기본값은 `http://localhost:3000/auth/reset-password`입니다.
Supabase Authentication → URL Configuration → Redirect URLs에 이 주소를 등록하는 것을 권장합니다.
미등록 시 Supabase가 Site URL로 돌아가므로, Site URL 역시 이 프론트 주소여야 합니다.
프론트 공통 레이아웃은 홈으로 도착한 recovery 링크를 재설정 화면으로 전달합니다.
운영 환경에서는 HTTPS 사이트 주소로 Site URL, Redirect URLs, PASSWORD_RESET_URL을 함께 변경하세요.

링크의 access token은 즉시 주소창에서 제거하고, Supabase `/user`로 검증한 뒤 별도의 HttpOnly 쿠키로 보관합니다.
재설정은 Supabase 검증이 완료된 토큰의 `amr=recovery` 또는 `otp`, 사용자 ID, 15분 이내 인증 시각을 확인합니다.
Supabase 기본 implicit 이메일 링크는 `otp`로 발급되므로 이를 허용합니다. 이는 최근 OTP 인증도 재설정 권한으로 인정하는 정책입니다.
참고: https://github.com/supabase/auth/blob/master/internal/api/verify.go (`verifyGet`, `verifyPost`).
프론트는 새로고침 시 별도 recovery 쿠키를 재검증하여 유효한 동안 재설정 화면을 복원합니다.
일반 로그인 토큰으로 재설정 API를 사용할 수 없습니다. 로그인 상태에서 변경할 때는
Supabase `/user`에 `current_password`를 함께 전달하여 기존 비밀번호를 확인합니다.
성공 후 프론트 쿠키를 삭제하고 새 비밀번호로 다시 로그인하도록 안내합니다.
새 비밀번호는 8~128자이며 Supabase 프로젝트의 추가 비밀번호 정책도 적용됩니다.
실제 비밀번호 변경 후 `.env.signup-test`의 테스트 비밀번호는 자동 갱신되지 않습니다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

외부 요청을 MockTransport로 대체하므로 실제 계정을 생성하거나 DB를 변경하지 않습니다.
실제 프로젝트의 키·가동 상태·스키마가 백업과 같은지는 별도 연결 확인이 필요합니다.

참고: https://supabase.com/docs/guides/auth/passwords 및 https://supabase.com/docs/guides/getting-started/api-keys
