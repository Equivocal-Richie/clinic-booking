from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlmodel import Session

from ..config import get_settings
from ..db import get_session
from ..models import Appointment, User, UserRole
from ..ratelimit import limiter
from ..schemas.appointment import (
    AppointmentCreate,
    AppointmentRead,
    CancelRequest,
    RescheduleRequest,
)
from ..schemas.error import ErrorResponse
from ..services import booking, idempotency
from ..services.timeutils import to_utc, utcnow
from .deps import ensure_can_act_on_patient, get_current_user

router = APIRouter(prefix="/appointments", tags=["appointments"])
_settings = get_settings()

_ERRORS = {
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


def _resolve_patient_id(current: User, requested: int) -> int:
    """Patients may only book for themselves; staff may book for any patient."""
    if current.role == UserRole.staff:
        return requested
    if current.patient_id is None or requested != current.patient_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Patients may only book for themselves",
        )
    return current.patient_id


@router.post(
    "",
    response_model=AppointmentRead,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
    summary="Book a slot (supports Idempotency-Key)",
)
@limiter.limit(_settings.rate_limit_booking)
def create_appointment(
    request: Request,
    payload: AppointmentCreate,
    session: Session = Depends(get_session),
    current: User = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    patient_id = _resolve_patient_id(current, payload.patient_id)
    tz = _settings.tz
    start_utc = to_utc(payload.start_time, tz)

    fp = idempotency.fingerprint(
        {"doctor_id": payload.doctor_id, "patient_id": patient_id, "start": start_utc}
    )
    if idempotency_key:
        existing = idempotency.try_begin(session, current.id, idempotency_key, fp)
        if existing is not None:
            if existing.request_fingerprint != fp:
                raise HTTPException(
                    status_code=422,
                    detail="Idempotency-Key reused with a different request body",
                )
            if existing.status == "completed" and existing.response_body:
                import json

                return JSONResponse(
                    status_code=existing.response_status or 201,
                    content=json.loads(existing.response_body),
                )
            raise HTTPException(
                status_code=409,
                detail="A request with this Idempotency-Key is still being processed",
            )

    try:
        appt = booking.create_appointment(
            session,
            doctor_id=payload.doctor_id,
            patient_id=patient_id,
            start_at_utc=start_utc,
            now=utcnow(),
        )
    except Exception:
        if idempotency_key:
            idempotency.abort(session, current.id, idempotency_key)
        raise

    body = AppointmentRead.model_validate(appt).model_dump(mode="json")
    if idempotency_key:
        idempotency.complete(session, current.id, idempotency_key, 201, body)
    return JSONResponse(status_code=201, content=body)


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
    current: User = Depends(get_current_user),
) -> AppointmentRead:
    appt = session.get(Appointment, appointment_id)
    if appt is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    ensure_can_act_on_patient(current, appt.patient_id)
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
    current: User = Depends(get_current_user),
) -> AppointmentRead:
    appt = session.get(Appointment, appointment_id)
    if appt is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    ensure_can_act_on_patient(current, appt.patient_id)
    new_start_utc = to_utc(payload.start_time, _settings.tz)
    appt = booking.reschedule_appointment(
        session, appointment_id, new_start_at_utc=new_start_utc, now=utcnow()
    )
    return AppointmentRead.model_validate(appt)
