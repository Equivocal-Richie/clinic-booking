from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from ..config import get_settings
from ..db import get_session
from ..schemas.appointment import (
    AppointmentCreate,
    AppointmentRead,
    CancelRequest,
    RescheduleRequest,
)
from ..schemas.error import ErrorResponse
from ..services import booking
from ..services.timeutils import to_utc, utcnow

router = APIRouter(prefix="/appointments", tags=["appointments"])

_ERRORS = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


@router.post(
    "",
    response_model=AppointmentRead,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
    summary="Book a slot",
)
def create_appointment(
    payload: AppointmentCreate, session: Session = Depends(get_session)
) -> AppointmentRead:
    tz = get_settings().tz
    start_utc = to_utc(payload.start_time, tz)
    appt = booking.create_appointment(
        session,
        doctor_id=payload.doctor_id,
        patient_id=payload.patient_id,
        start_at_utc=start_utc,
        now=utcnow(),
    )
    return AppointmentRead.model_validate(appt)


@router.patch(
    "/{appointment_id}/cancel",
    response_model=AppointmentRead,
    responses=_ERRORS,
    summary="Cancel an appointment (frees the slot)",
)
def cancel_appointment(
    appointment_id: int,
    payload: CancelRequest,
    session: Session = Depends(get_session),
) -> AppointmentRead:
    appt = booking.cancel_appointment(
        session, appointment_id, reason=payload.reason, now=utcnow()
    )
    return AppointmentRead.model_validate(appt)


@router.patch(
    "/{appointment_id}/reschedule",
    response_model=AppointmentRead,
    responses=_ERRORS,
    summary="Move an appointment to a new slot",
)
def reschedule_appointment(
    appointment_id: int,
    payload: RescheduleRequest,
    session: Session = Depends(get_session),
) -> AppointmentRead:
    tz = get_settings().tz
    new_start_utc = to_utc(payload.start_time, tz)
    appt = booking.reschedule_appointment(
        session, appointment_id, new_start_at_utc=new_start_utc, now=utcnow()
    )
    return AppointmentRead.model_validate(appt)
