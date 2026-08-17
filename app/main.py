from __future__ import annotations

import secrets
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.errors import error_response
from app.api.routes import router
from app.config import RATE_LIMIT_PER_MINUTE, Settings
from app.providers.llm import LLMProvider
from app.providers.mock import MockProvider
from app.services.rate_limit import SlidingWindowRateLimiter
from app.services.reviews import ReviewService


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    application = FastAPI(title="AI Diff Review Service", version="1.0.0")
    application.state.started_at = time.monotonic()
    application.state.settings = resolved
    application.state.review_service = ReviewService(
        providers={"mock": MockProvider(), "llm": LLMProvider(resolved)}
    )
    application.state.rate_limiter = SlidingWindowRateLimiter(RATE_LIMIT_PER_MINUTE)

    @application.middleware("http")
    async def authenticate_v1(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path == "/v1" or request.url.path.startswith("/v1/"):
            authorization = request.headers.get("authorization", "")
            expected = f"Bearer {resolved.bearer_token}"
            if not resolved.bearer_token or not secrets.compare_digest(authorization, expected):
                return error_response(401, "unauthorized", "Missing or invalid bearer token")
        return await call_next(request)

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "internal"
        return error_response(exc.status_code, code, str(exc.detail))

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(422, "invalid_diff", "Invalid request")

    @application.exception_handler(Exception)
    async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return error_response(500, "internal", "Internal server error")

    application.include_router(router)
    return application


app = create_app()
