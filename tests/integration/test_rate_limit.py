"""Rate limiting mechanism (self-contained; the main suite runs with limits off).

Builds a tiny app with the same slowapi wiring as production but a low limit, to
prove that requests past the limit receive 429.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address


def _build_app() -> FastAPI:
    limiter = Limiter(key_func=get_remote_address, default_limits=["3/minute"], enabled=True)
    app = FastAPI()
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def _handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(status_code=429, content={"error": {"code": "rate_limited"}})

    @app.get("/ping")
    def ping(request: Request) -> dict[str, bool]:
        return {"ok": True}

    return app


def test_requests_past_the_limit_get_429():
    client = TestClient(_build_app())
    codes = [client.get("/ping").status_code for _ in range(5)]
    assert codes.count(200) == 3
    assert codes.count(429) == 2
