# COMBEE deployment: Render API + Vercel web

Repositories are separate: COMBEE-WEB/backend and COMBEE-WEB/frontend.
Deploy the latest local source, not the previous remote scaffolding.

## Backend (Render)

Create a Python Web Service from the backend repository, or use render.yaml
as a Blueprint. Root directory is the repository root (leave blank).
Build: pip install -r requirements.txt
Start: uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
Health check: /health. Select the Free plan explicitly.

Set in Render's environment editor, never in Git:
- SUPABASE_URL: existing project URL
- SUPABASE_PUBLISHABLE_KEY: existing publishable key
- OPENAI_API_KEY: existing server API key
- OPENAI_MODEL: gpt-4.1-mini
- PYTHON_VERSION: 3.12.14
- CORS_ORIGINS: exact frontend HTTPS origin
- PASSWORD_RESET_URL: frontend HTTPS origin + /auth/reset-password

Do not copy the import-only Supabase secret/service-role key or signup test
credentials into runtime settings. The application uses publishable + user RLS.
Keep one worker/instance: AI limits are currently in-process.

## Frontend (Vercel)

Deploy frontend repository root as Next.js. Build command npm run build.
Do not select static export: auth and API routes require the Node server runtime.
Use the Hobby/free option for this demo. Organization-owned Git repositories
may be unavailable on Hobby Git integration; check the dashboard before connecting.
No paid upgrade is implied by these instructions.

Production environment variables:
- BACKEND_URL: deployed backend HTTPS URL (no trailing slash)
- APP_ORIGIN: exact production frontend HTTPS origin (no path)

vercel.json allows up to 300 seconds for API handlers, covering AI generation.
Keep environment values scoped to production. Preview deployments require their
own matching origin and appropriate backend configuration if used for writes.

## Supabase Auth

Set Authentication > URL Configuration > Site URL to the final frontend URL.
Add frontend URL + /auth/reset-password to Redirect URLs. Preserve localhost
entries while local development remains in use. Keep the configured custom SMTP
and OTP email template. Redeploy/restart after changing environment variables.

## Verify

1. Backend /health and /api/parts?limit=1 return 200.
2. Open frontend, then list parts and both community boards.
3. Sign in, load saved estimates, verify same-origin POSTs work over HTTPS.
4. Generate one estimate, reopen the saved result, and confirm home history.
5. Verify password recovery with a user-requested email, not repeated probes.

The Free Render service sleeps after 15 minutes without inbound traffic. Open
the backend /health before a demonstration and wait for startup before signing
in. The 15-second app request timeout can otherwise expire during cold startup.
No automated keep-alive loop is configured.

References:
- https://render.com/docs/deploy-fastapi
- https://render.com/docs/free
- https://vercel.com/docs/functions/configuring-functions/duration

Status: configuration prepared locally; public URLs and account deployment
verification must be filled in after the actual hosting services are created.
