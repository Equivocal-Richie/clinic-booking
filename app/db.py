"""Database engine and session management."""
from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session, create_engine

from .config import get_settings

_settings = get_settings()

# pool_pre_ping guards against stale connections (important on platforms like
# Render where the managed Postgres may drop idle connections).
engine = create_engine(_settings.sqlalchemy_url, pool_pre_ping=True, echo=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yields a session and ensures it is closed."""
    with Session(engine) as session:
        yield session
