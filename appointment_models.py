from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def normalize_utc_iso(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class AppointmentStatus(str, Enum):
    REQUESTED = "requested"
    CONFIRMED = "confirmed"
    RESCHEDULED = "rescheduled"
    CANCELLED_BY_STUDENT = "cancelled_by_student"
    CANCELLED_BY_STAFF = "cancelled_by_staff"
    ATTENDED = "attended"
    NO_SHOW = "no_show"
    REJECTED = "rejected"


ACTIVE_APPOINTMENT_STATUSES = {
    AppointmentStatus.REQUESTED.value,
    AppointmentStatus.CONFIRMED.value,
    AppointmentStatus.RESCHEDULED.value,
}


FINAL_APPOINTMENT_STATUSES = {
    AppointmentStatus.CANCELLED_BY_STUDENT.value,
    AppointmentStatus.CANCELLED_BY_STAFF.value,
    AppointmentStatus.ATTENDED.value,
    AppointmentStatus.NO_SHOW.value,
    AppointmentStatus.REJECTED.value,
}


class _AppointmentBaseModel(BaseModel):
    class Config:
        use_enum_values = True


class AppointmentStudent(_AppointmentBaseModel):
    matricula: str
    nombre: str = ""
    correo_institucional: str = ""
    programa: str = ""
    campus: str = ""


class AppointmentRequestedBy(_AppointmentBaseModel):
    source: str = "carnet_web"
    email_session: str = ""
    role: str = "student"


class AppointmentHistoryEntry(_AppointmentBaseModel):
    from_status: Optional[str] = Field(default=None, alias="from")
    to: str
    actor: str
    actor_role: str
    message: Optional[str] = None
    created_at: str


class AppointmentResponse(_AppointmentBaseModel):
    id: str
    type: str = "appointment"
    student: AppointmentStudent
    requested_by: AppointmentRequestedBy
    area: str
    reason_category: str
    reason_text: str
    preferred_date: str = ""
    preferred_time_block: str = ""
    scheduled_start: Optional[str] = None
    scheduled_end: Optional[str] = None
    status: AppointmentStatus
    priority: str = "normal"
    assigned_to: Optional[str] = None
    created_at: str
    updated_at: str
    created_by: str = "carnet_web"
    updated_by: Optional[str] = None
    cancellation_reason: Optional[str] = None
    reschedule_reason: Optional[str] = None
    source_referral_id: Optional[str] = None
    history: List[Dict[str, Any]] = []


class AppointmentScheduleUpdate(_AppointmentBaseModel):
    scheduled_start: str
    scheduled_end: str
    assigned_to: Optional[str] = Field(default=None, max_length=120)
    message: Optional[str] = Field(default=None, max_length=500)

    @validator("scheduled_start", "scheduled_end")
    def normalize_schedule_date(cls, value):
        normalized = normalize_utc_iso(value)
        if not normalized:
            raise ValueError("La fecha programada es obligatoria")
        return normalized


class AppointmentRescheduleUpdate(AppointmentScheduleUpdate):
    reschedule_reason: Optional[str] = Field(default=None, max_length=500)


class AppointmentCancelUpdate(_AppointmentBaseModel):
    cancellation_reason: Optional[str] = Field(default=None, max_length=500)


class AppointmentSimpleStatusUpdate(_AppointmentBaseModel):
    message: Optional[str] = Field(default=None, max_length=500)
