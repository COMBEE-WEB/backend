# AI estimates

Configure `OPENAI_API_KEY` and optionally `OPENAI_MODEL` in backend/.env.
The default is `gpt-4.1-mini`; secrets never enter the frontend bundle.
Restart the backend after changing the environment.

The frontend offers two conversation modes: /ai/chat sends bounded conversation
history to authenticated POST /api/estimates/chat; /ai/question diagnoses PC
experience and presents a level-specific questionnaire. Both require an explicit
generate action before calling POST /api/estimates and show the result in chat.
Chat uses the same server-side OpenAI configuration, a three-second per-user
cooldown, and the shared in-flight request limit. Chat text is session-local;
generated estimate snapshots are saved and remain accessible from the home page.

Onboarding questions are transcribed from the supplied COMBEE FigJam image in
app/data/onboarding.json. Beginner self-selection skips the quiz; intermediate
and advanced each have five two-point questions, pass at six points, and fall
back one level on failure. POST /api/estimates/onboarding grades on the server;
GET strips answer keys. Completed diagnosis and questionnaire preferences are
stored through the user's authenticated Supabase Auth metadata under
combee_onboarding_v1 (no schema migration). These are user-editable UX preferences,
not trusted authorization roles. Home prompts accounts without a saved diagnosis.
Existing levels skip the quiz; /level and the result screen allow reassessment.
Beginner has eight survey questions, intermediate five, and advanced multi-select
keyword groups. Exact budget/use/program/owned conditions are confirmed afterwards.
POST /api/estimates/onboarding/preferences validates the level's complete answers.
The /ai/chat?guided=1 handoff reloads saved conditions and passes preferences to
conversation and generation. Questionnaire completion itself incurs no AI calls.

Implementation uses OpenAI Responses with strict JSON-schema output and
`store: false`. Reference: https://developers.openai.com/api/docs/guides/structured-outputs

Authenticated POST `/api/estimates` accepts budget_won (300000–20000000),
purpose (게임 / 영상·디자인 / 개발 / 사무·학습), programs and owned (max 1000 chars each).
An initial model call proposes two search terms per category. The server queries
active Supabase records and a second model call chooses only those IDs. IDs and
categories are validated again server-side. Partial results explicitly list
missing slots. RAM is selected as one kit, quantity 1.
When family-name searches find no matches, up to 24 real category records are
provided as fallback candidates. The overview is generated from server-verified
selection status, so model prose cannot claim an unknown total meets the budget.

Only basic socket, RAM generation and cooler socket checks are implemented.
BIOS support, clearances, power/connectors, memory capacity and storage interfaces
remain unverified. Owned-part text is advisory; this version recommends a new
build and does not deduct existing parts. No purchase-ready or budget guarantee.
Prices come only from parts.lowest_price; incomplete prices produce null totals.

The generated snapshot is saved in one private pc_builds row using the user's
Supabase token and RLS, never the admin key. The versioned JSON snapshot lives in
description; pc_build_items is not populated in this version. Because the legacy
total_price column is NOT NULL, unknown is stored there as 0; the snapshot and API
preserve null. Consumers must use the snapshot total, not this legacy fallback.
If saving fails, the recommendation is returned with saved=false and a warning.

GET `/api/estimates` lists the caller's latest 10 saved builds; GET
`/api/estimates/{id}` enforces the caller's user_id in addition to RLS.
The home dashboard uses this list; `/ai/estimates/{id}` restores the snapshot.
Generation is limited to one attempt per user per minute and three in-flight
requests per process. Shared distributed limits are needed before multi-worker
production deployment. Frontend prevents duplicate submissions and requires
same-origin POSTs; backend independently verifies authentication before model use.

Tests use mocked OpenAI/Supabase transports, including invalid IDs, category
mismatch, missing prices, socket conflicts, auth isolation and private saves.
Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'`
