from __future__ import annotations

from fastapi import FastAPI

from .api import appointments, doctors, patients
from .config import get_settings
from .errors import register_exception_handlers


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Clinic appointment booking API. Interactive docs at /docs. "
            "Slot availability is derived (never pre-generated); slot "
            "exclusivity is enforced by a Postgres partial unique index."
        ),
    )

    register_exception_handlers(app)

    @app.get("/health", tags=["meta"], summary="Liveness/readiness probe")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", tags=["meta"], include_in_schema=False)
    def root() -> dict[str, str]:
        return {"service": settings.app_name, "docs": "/docs", "health": "/health"}

    app.include_router(appointments.router)
    app.include_router(doctors.router)
    app.include_router(patients.router)
    return app


app = create_app()
