from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class ReferralStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    RECEIVED = "received"
    ACCEPTED = "accepted"
    SCHEDULED = "scheduled"
    ATTENDED = "attended"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class ReferralPriority(str, Enum):
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"
    URGENTE = "urgente"


class ReferralArea(str, Enum):
    MEDICO = "medico"
    PSICOLOGIA = "psicologia"
    NUTRICION = "nutricion"
    ODONTOLOGIA = "odontologia"
    ATENCION_ESTUDIANTIL = "atencion_estudiantil"


FINAL_REFERRAL_STATUSES = {
    ReferralStatus.CLOSED.value,
    ReferralStatus.CANCELLED.value,
}


VALID_REFERRAL_TRANSITIONS = {
    ReferralStatus.DRAFT.value: {ReferralStatus.SENT.value, ReferralStatus.CANCELLED.value},
    ReferralStatus.SENT.value: {ReferralStatus.RECEIVED.value, ReferralStatus.CANCELLED.value},
    ReferralStatus.RECEIVED.value: {ReferralStatus.ACCEPTED.value, ReferralStatus.CANCELLED.value},
    ReferralStatus.ACCEPTED.value: {
        ReferralStatus.SCHEDULED.value,
        ReferralStatus.ATTENDED.value,
        ReferralStatus.CANCELLED.value,
    },
    ReferralStatus.SCHEDULED.value: {ReferralStatus.ATTENDED.value, ReferralStatus.CANCELLED.value},
    ReferralStatus.ATTENDED.value: {ReferralStatus.CLOSED.value, ReferralStatus.CANCELLED.value},
    ReferralStatus.CLOSED.value: set(),
    ReferralStatus.CANCELLED.value: set(),
}


class _ReferralBaseModel(BaseModel):
    class Config:
        use_enum_values = True


class ReferralStudent(_ReferralBaseModel):
    matricula: str = Field(..., min_length=1, max_length=40)
    nombre: str = Field(..., min_length=1, max_length=160)
    correo: Optional[str] = Field(default=None, max_length=160)
    programa: Optional[str] = Field(default=None, max_length=160)
    campus: Optional[str] = Field(default=None, max_length=120)
    unidadAcademica: Optional[str] = Field(default=None, max_length=160)


class ReferralActor(_ReferralBaseModel):
    area: ReferralArea
    userId: str = Field(..., min_length=1, max_length=120)
    userName: str = Field(..., min_length=1, max_length=160)
    role: str = Field(..., min_length=1, max_length=80)


class ReferralDestination(_ReferralBaseModel):
    area: ReferralArea
    assignedUserId: Optional[str] = Field(default=None, max_length=120)
    assignedUserName: Optional[str] = Field(default=None, max_length=160)


class StatusHistoryItem(_ReferralBaseModel):
    status: ReferralStatus
    previousStatus: Optional[ReferralStatus] = None
    at: str
    byUserId: str
    byUserName: str
    byRole: str
    area: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=1000)
    appointmentId: Optional[str] = Field(default=None, max_length=120)
    metadata: Optional[Dict[str, Any]] = None


class CounterReferralCreate(_ReferralBaseModel):
    summary: str = Field(..., min_length=1, max_length=4000)
    recommendations: Optional[str] = Field(default=None, max_length=4000)
    followUpRequired: bool = False
    followUpArea: Optional[ReferralArea] = None
    nextSuggestedAction: Optional[str] = Field(default=None, max_length=1000)


class CounterReferral(_ReferralBaseModel):
    responseArea: ReferralArea
    responseUserId: str
    responseUserName: str
    responseRole: str
    summary: str
    recommendations: Optional[str] = None
    followUpRequired: bool = False
    followUpArea: Optional[ReferralArea] = None
    nextSuggestedAction: Optional[str] = None
    createdAt: str


class ReferralCreate(_ReferralBaseModel):
    student: ReferralStudent
    originArea: ReferralArea
    destinationArea: ReferralArea
    priority: ReferralPriority
    reason: str = Field(..., min_length=1, max_length=4000)
    observations: Optional[str] = Field(default=None, max_length=4000)
    send: bool = True

    @validator("reason")
    def validate_reason(cls, value):
        text = str(value).strip()
        if not text:
            raise ValueError("El motivo es obligatorio")
        return text


class ReferralUpdateStatus(_ReferralBaseModel):
    status: ReferralStatus
    note: Optional[str] = Field(default=None, max_length=1000)
    reason: Optional[str] = Field(default=None, max_length=1000)
    appointmentId: Optional[str] = Field(default=None, max_length=120)


class Referral(_ReferralBaseModel):
    id: str
    type: str = "referral"
    student: ReferralStudent
    origin: ReferralActor
    destination: ReferralDestination
    priority: ReferralPriority
    reason: str
    observations: Optional[str] = None
    status: ReferralStatus
    createdAt: str
    updatedAt: str
    receivedAt: Optional[str] = None
    acceptedAt: Optional[str] = None
    scheduledAt: Optional[str] = None
    attendedAt: Optional[str] = None
    closedAt: Optional[str] = None
    cancelledAt: Optional[str] = None
    cancellationReason: Optional[str] = None
    appointmentId: Optional[str] = None
    counterReferral: Optional[CounterReferral] = None
    statusHistory: List[StatusHistoryItem] = []
    createdBy: str
    createdByRole: str
    updatedBy: Optional[str] = None
    updatedByRole: Optional[str] = None
    schemaVersion: int = 1
