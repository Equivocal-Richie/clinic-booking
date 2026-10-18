from __future__ import annotations

from datetime import date as date_cls
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from ..config import get_settings
from ..db import get_session
from ..models import User
from ..schemas.availability import AvailabilityResponse, Slot
from ..schemas.error import ErrorResponse
from ..services import availability
from ..services.timeutils import utcnow
from .deps import get_current_user

router = APIRouter(prefix="/doctors", tags=["doctors"])


@router.get(
    "/{doctor_id}/availability",
    response_model=AvailabilityResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="List available 30-minute slots for a doctor on a date",
)
def get_availability(
    doctor_id: int,
    date: date_cls = Query(
        ..., description="Day to check, YYYY-MM-DD (clinic timezone)"
    ),
    session: Session = Depends(get_session),
    _current: User = Depends(get_current_user),
) -> AvailabilityResponse:
    settings = get_settings()
    starts = availability.compute_availability(
        session, doctor_id, on_date=date, now=utcnow()
    )
    duration = settings.slot_duration_minutes
    slots = [
        Slot(start_time=s, end_time=s + timedelta(minutes=duration)) for s in starts
    ]
    return AvailabilityResponse(
        doctor_id=doctor_id,
        date=date,
        slot_duration_minutes=duration,
        available_slots=slots,
    )
