from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, parts, estimates, onboarding, community
from app.services.estimates import EstimateEngine
from app.config import Settings
from app.services.supabase import SupabaseGateway


def create_app(settings: Settings | None = None, transport=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=10, transport=transport) as client:
            app.state.supabase = SupabaseGateway(settings, client)
            yield

    app = FastAPI(title='COMBEE API', lifespan=lifespan)
    app.state.estimate_engine = EstimateEngine(settings)
    app.state.estimate_active = set()
    app.state.estimate_times = {}
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type'])

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # FastAPI's default validation response can echo password inputs.
        return JSONResponse(status_code=422, content={'detail': [
            {'loc': list(error['loc']), 'msg': error['msg'], 'type': error['type']}
            for error in exc.errors()
        ]})

    @app.middleware('http')
    async def no_cache_auth(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith('/api/auth'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/health', tags=['health'])
    def get_health():
        return {'status': 'ok'}

    app.include_router(auth.router, prefix='/api')
    app.include_router(parts.router, prefix='/api')
    app.include_router(onboarding.router, prefix='/api')
    app.include_router(estimates.router, prefix='/api')
    app.include_router(community.router, prefix='/api')
    return app


app = create_app()
