from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .api import appointments, auth, doctors, patients
from .config import get_settings
from .errors import register_exception_handlers
from .ratelimit import limiter


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        description=(
            "Clinic appointment booking API. Interactive docs at /docs. "
            "Slot availability is derived (never pre-generated); slot "
            "exclusivity is enforced by a Postgres partial unique index. "
            "JWT auth with patient/staff roles, idempotent booking, rate "
            "limiting, and paginated reads."
        ),
    )

    # Rate limiting: attach limiter, apply default limits via middleware, and
    # return a consistent 429 body.
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": "rate_limited",
                    "message": f"Rate limit exceeded: {exc.detail}",
                }
            },
        )

    register_exception_handlers(app)

    @app.get("/health", tags=["meta"], summary="Liveness/readiness probe")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", tags=["meta"], include_in_schema=False)
    def root() -> dict[str, str]:
        return {"service": settings.app_name, "docs": "/docs", "health": "/health"}

    app.include_router(auth.router)
    app.include_router(appointments.router)
    app.include_router(doctors.router)
    app.include_router(patients.router)
    return app


app = create_app()
