"""Rate limiting (slowapi).

Keyed by the real client IP (honouring X-Forwarded-For, since the app runs
behind Render's proxy). A global default limit protects every route; booking
writes get a tighter per-route limit.

Note on scale: the default storage is in-memory, which is PER WORKER — with
multiple gunicorn workers/instances the effective limit multiplies and is not
shared. For a hard global limit set RATE_LIMIT_STORAGE_URI to a Redis URL; the
limiter then coordinates across workers. (Same principle as slot locking: shared
guarantees need shared state.)
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from .config import get_settings

_settings = get_settings()


def _client_key(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=_client_key,
    default_limits=[_settings.rate_limit_default],
    storage_uri=_settings.rate_limit_storage_uri,
    enabled=_settings.rate_limit_enabled,
)
