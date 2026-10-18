"""Translate exceptions into one consistent HTTP error envelope.

Every error (domain rule, auth, not-found, schema validation) returns:
    {"error": {"code": "<slug>", "message": "<human message>"}}

HTTP status strategy:
  - 422: request body/params fail SCHEMA validation (Pydantic).
  - 400: well-formed request violates a BUSINESS rule (past slot, lead time).
  - 401/403: not authenticated / not allowed.
  - 404: referenced entity does not exist.
  - 409: slot already taken, or illegal state transition.
  - 429: rate limit exceeded (handler registered in main).
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .services.exceptions import (
    ConflictStateError,
    DomainError,
    NotFoundError,
    SlotTakenError,
    ValidationError,
)

_DOMAIN_STATUS: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ValidationError: 400,
    SlotTakenError: 409,
    ConflictStateError: 409,
}

_STATUS_CODE_SLUG = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
}


def _payload(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _handle_domain(_: Request, exc: DomainError) -> JSONResponse:
        status = _DOMAIN_STATUS.get(type(exc), 400)
        return JSONResponse(status_code=status, content=_payload(exc.code, exc.message))

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        slug = _STATUS_CODE_SLUG.get(exc.status_code, "error")
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(slug, str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Surface the first error concisely; full list under 'fields'.
        errors = exc.errors()
        first = errors[0] if errors else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        msg = first.get("msg", "Invalid request")
        message = f"{loc}: {msg}" if loc else msg
        body = _payload("validation_error", message)
        body["error"]["fields"] = [
            {"field": ".".join(str(p) for p in e.get("loc", []) if p != "body"),
             "message": e.get("msg", "")}
            for e in errors
        ]
        return JSONResponse(status_code=422, content=body)
