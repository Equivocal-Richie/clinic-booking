from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from ..config import get_settings
from ..db import get_session
from ..models import User
from ..schemas.appointment import AppointmentRead, PaginatedAppointments
from ..schemas.error import ErrorResponse
from ..services import booking
from ..services.timeutils import utcnow
from .deps import ensure_can_act_on_patient, get_current_user

router = APIRouter(prefix="/patients", tags=["patients"])
_settings = get_settings()


@router.get(
    "/{patient_id}/appointments",
    response_model=PaginatedAppointments,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="(Bonus) A patient's upcoming appointments, soonest first (paginated)",
)
def list_patient_appointments(
    patient_id: int,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
    limit: int = Query(default=None, ge=1, le=_settings.max_page_size),
    offset: int = Query(default=0, ge=0),
) -> PaginatedAppointments:
    ensure_can_act_on_patient(current, patient_id)
    page_size = limit or _settings.default_page_size
    appts, has_more = booking.upcoming_for_patient(
        session, patient_id, now=utcnow(), limit=page_size, offset=offset
    )
    return PaginatedAppointments(
        items=[AppointmentRead.model_validate(a) for a in appts],
        limit=page_size,
        offset=offset,
        has_more=has_more,
    )
