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


class TicketEstado(str, Enum):
    ABIERTO = "abierto"
    EN_REVISION = "en_revision"
    EN_PROCESO = "en_proceso"
    ASIGNADO = "asignado"
    EN_ATENCION = "en_atencion"
    PENDIENTE_PACIENTE = "pendiente_paciente"
    RESUELTO = "resuelto"
    CERRADO = "cerrado"
    CANCELADO = "cancelado"


class TicketCategoria(str, Enum):
    PSICOLOGIA = "psicologia"
    MEDICINA = "medicina"
    NUTRICION = "nutricion"
    VACUNACION = "vacunacion"
    PROMOCION_SALUD = "promocion_salud"
    SOPORTE_CARNET = "soporte_carnet"
    ADMINISTRATIVO = "administrativo"
    OTRO = "otro"


class TicketPrioridad(str, Enum):
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"
    URGENTE = "urgente"


class AppointmentMode(str, Enum):
    PRESENCIAL = "presencial"
    VIRTUAL = "virtual"


class TicketSenderRole(str, Enum):
    ALUMNO = "alumno"
    PSICOLOGIA = "psicologia"
    MEDICINA = "medicina"
    NUTRICION = "nutricion"
    VACUNACION = "vacunacion"
    PROMOCION = "promocion"
    ADMINISTRADOR = "administrador"


class TicketFollowupVisibility(str, Enum):
    INTERNAL = "internal"
    STUDENT = "student"


class _TicketBaseModel(BaseModel):
    class Config:
        use_enum_values = True


class TicketCreate(_TicketBaseModel):
    patientId: Optional[str] = Field(default=None, max_length=80)
    matricula: str = Field(..., min_length=1, max_length=40)
    nombrePaciente: str = Field(..., min_length=1, max_length=160)
    campus: str = Field(..., min_length=1, max_length=80)
    categoria: TicketCategoria
    prioridad: TicketPrioridad = TicketPrioridad.MEDIA
    titulo: str = Field(..., min_length=3, max_length=160)
    descripcionInicial: str = Field(..., min_length=3, max_length=3000)
    assignedTo: Optional[str] = Field(default=None, max_length=120)
    assignedArea: Optional[str] = Field(default=None, max_length=80)
    appointmentMode: Optional[AppointmentMode] = None
    appointmentAtUtc: Optional[str] = None
    videoCallUrl: Optional[str] = Field(default=None, max_length=500)

    @validator("appointmentAtUtc")
    def normalize_appointment_at(cls, value):
        return normalize_utc_iso(value)

    @validator("videoCallUrl")
    def validate_video_call_url(cls, value):
        if value is None or not str(value).strip():
            return None
        text = str(value).strip()
        if not text.startswith("https://"):
            raise ValueError("videoCallUrl debe iniciar con https://")
        return text


class TicketMessageCreate(_TicketBaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    attachmentUrl: Optional[str] = Field(default=None, max_length=500)

    @validator("attachmentUrl")
    def validate_attachment_url(cls, value):
        if value is None or not str(value).strip():
            return None
        text = str(value).strip()
        if not text.startswith("https://"):
            raise ValueError("attachmentUrl debe iniciar con https://")
        return text


class TicketAssignUpdate(_TicketBaseModel):
    assignedTo: Optional[str] = Field(default=None, max_length=120)
    assignedArea: Optional[str] = Field(default=None, max_length=80)

    @validator("assignedArea", always=True)
    def require_assignment_target(cls, value, values):
        if not value and not values.get("assignedTo"):
            raise ValueError("Debe indicar assignedTo o assignedArea")
        return value


class TicketStatusUpdate(_TicketBaseModel):
    estado: TicketEstado


class TicketFollowupCreate(_TicketBaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    visibility: TicketFollowupVisibility = TicketFollowupVisibility.INTERNAL


class TicketAppointmentUpdate(_TicketBaseModel):
    appointmentMode: AppointmentMode
    appointmentAtUtc: str

    @validator("appointmentAtUtc")
    def normalize_required_appointment_at(cls, value):
        normalized = normalize_utc_iso(value)
        if not normalized:
            raise ValueError("appointmentAtUtc es obligatorio")
        return normalized


class TicketVideoCallUpdate(_TicketBaseModel):
    videoCallUrl: str = Field(..., min_length=8, max_length=500)

    @validator("videoCallUrl")
    def validate_required_video_call_url(cls, value):
        text = str(value).strip()
        if not text.startswith("https://"):
            raise ValueError("videoCallUrl debe iniciar con https://")
        return text


class TicketResponse(_TicketBaseModel):
    id: str
    ticketNumber: str
    patientId: Optional[str] = None
    matricula: str
    nombrePaciente: str
    campus: str
    categoria: TicketCategoria
    prioridad: TicketPrioridad
    estado: TicketEstado
    titulo: str
    descripcionInicial: str
    assignedTo: Optional[str] = None
    assignedArea: Optional[str] = None
    appointmentMode: Optional[AppointmentMode] = None
    appointmentAtUtc: Optional[str] = None
    videoCallUrl: Optional[str] = None
    createdAtUtc: str
    updatedAtUtc: str
    closedAtUtc: Optional[str] = None
    createdBy: str
    createdByRole: Optional[str] = None
    lastMessageAtUtc: Optional[str] = None
    lastMessagePreview: Optional[str] = None
    lastFollowupAtUtc: Optional[str] = None
    statusHistory: Optional[List[Dict[str, Any]]] = None
    deleted: bool = False
    schemaVersion: int = 1


class TicketMessageResponse(_TicketBaseModel):
    id: str
    ticketId: str
    senderId: str
    senderRole: TicketSenderRole
    senderName: str
    message: str
    createdAtUtc: str
    readAtUtc: Optional[str] = None
    attachmentUrl: Optional[str] = None
    deleted: bool = False
    metadata: Optional[Dict[str, Any]] = None


class TicketFollowupResponse(_TicketBaseModel):
    id: str
    ticket_id: str
    author: str
    role: str
    message: str
    visibility: TicketFollowupVisibility
    created_at: str
    metadata: Optional[Dict[str, Any]] = None


class TicketDetailResponse(_TicketBaseModel):
    ticket: TicketResponse
    messages: List[TicketMessageResponse] = []
    followups: List[TicketFollowupResponse] = []
