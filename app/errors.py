"""Translate domain exceptions into consistent HTTP error responses.

HTTP status strategy (documented in README):
  - 422 Unprocessable Entity: request body/params fail SCHEMA validation
    (handled automatically by FastAPI/Pydantic).
  - 400 Bad Request: request is well-formed but violates a BUSINESS rule
    (past slot, outside working hours, lead time).
  - 404 Not Found: referenced doctor/patient/appointment does not exist.
  - 409 Conflict: slot already taken, or illegal state transition
    (cancel an already-cancelled appointment, reschedule a cancelled one).
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .services.exceptions import (
    ConflictStateError,
    DomainError,
    NotFoundError,
    SlotTakenError,
    ValidationError,
)

_STATUS_MAP: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ValidationError: 400,
    SlotTakenError: 409,
    ConflictStateError: 409,
}


def _error_payload(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        status = _STATUS_MAP.get(type(exc), 400)
        return JSONResponse(
            status_code=status, content=_error_payload(exc.code, exc.message)
        )
