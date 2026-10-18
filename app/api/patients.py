from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ..db import get_session
from ..schemas.appointment import AppointmentRead
from ..schemas.error import ErrorResponse
from ..services import booking
from ..services.timeutils import utcnow

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get(
    "/{patient_id}/appointments",
    response_model=list[AppointmentRead],
    responses={404: {"model": ErrorResponse}},
    summary="(Bonus) A patient's upcoming appointments, soonest first",
)
def list_patient_appointments(
    patient_id: int, session: Session = Depends(get_session)
) -> list[AppointmentRead]:
    appts = booking.upcoming_for_patient(session, patient_id, now=utcnow())
    return [AppointmentRead.model_validate(a) for a in appts]
