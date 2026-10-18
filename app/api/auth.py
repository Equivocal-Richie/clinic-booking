from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from ..db import get_session
from ..models import Patient, User, UserRole
from ..schemas.auth import PatientRegister, StaffCreate, Token, UserRead
from ..schemas.error import ErrorResponse
from ..security import create_access_token, hash_password, verify_password
from .deps import require_staff

router = APIRouter(prefix="/auth", tags=["auth"])


def _email_taken(session: Session, email: str) -> bool:
    return session.exec(select(User).where(User.email == email)).first() is not None


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
    summary="Self-register as a patient",
)
def register_patient(
    payload: PatientRegister, session: Session = Depends(get_session)
) -> UserRead:
    if _email_taken(session, payload.email):
        raise HTTPException(status_code=409, detail="Email already registered")
    patient = Patient(name=payload.name, email=payload.email, phone=payload.phone)
    session.add(patient)
    session.flush()
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=UserRole.patient,
        patient_id=patient.id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return UserRead(id=user.id, email=user.email, role=user.role, patient_id=user.patient_id)


@router.post("/login", response_model=Token, summary="Obtain a JWT access token")
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
) -> Token:
    # OAuth2 form uses "username"; we treat it as the email.
    user = session.exec(select(User).where(User.email == form.username)).first()
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(user.id, user.role.value)
    return Token(access_token=token)


@router.post(
    "/staff",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    responses={403: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    summary="Create a clinical-staff account (staff only)",
)
def create_staff(
    payload: StaffCreate,
    session: Session = Depends(get_session),
    _: User = Depends(require_staff),
) -> UserRead:
    if _email_taken(session, payload.email):
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=UserRole.staff,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return UserRead(id=user.id, email=user.email, role=user.role, patient_id=None)
