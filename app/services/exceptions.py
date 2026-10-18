"""Domain exceptions.

These are raised by the service layer and translated to HTTP responses by the
exception handlers in app.errors. Keeping them separate from HTTP concerns means
the booking logic can be unit-tested without a web stack.
"""
from __future__ import annotations


class DomainError(Exception):
    """Base class for all domain errors."""

    code = "domain_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    """A referenced entity (doctor, patient, appointment) does not exist. -> 404"""

    code = "not_found"


class ValidationError(DomainError):
    """A business rule was violated (bad slot, past time, lead time). -> 400"""

    code = "validation_error"


class SlotTakenError(DomainError):
    """The requested slot is already booked. -> 409"""

    code = "slot_taken"


class ConflictStateError(DomainError):
    """The entity is in a state that forbids this transition
    (e.g. cancelling an already-cancelled appointment). -> 409
    """

    code = "conflict"
