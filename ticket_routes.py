from dataclasses import dataclass
import logging
import os
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from jose import JWTError, jwt

from auth_models import Campus, TokenData, UserRole, has_permission
from auth_service import ALGORITHM, SECRET_KEY, oauth2_scheme
from ticket_models import (
    TicketAppointmentUpdate,
    TicketAssignUpdate,
    TicketCreate,
    TicketDetailResponse,
    TicketEstado,
    TicketFollowupCreate,
    TicketFollowupResponse,
    TicketMessageCreate,
    TicketMessageResponse,
    TicketResponse,
    TicketSenderRole,
    TicketStatusUpdate,
    TicketVideoCallUpdate,
    utc_now_iso,
)
from ticket_repository import (
    CosmosTicketRepository,
    TicketNotFoundError,
    generate_ticket_id,
    generate_ticket_message_id,
    generate_ticket_number,
)


router = APIRouter(prefix="/tickets", tags=["tickets"])

logger = logging.getLogger(__name__)

_repository = None

STUDENT_ROLE = "alumno"
STUDENT_ALLOWED_PERMISSIONS = {"tickets:create", "tickets:read", "tickets:reply"}
DEFAULT_STUDENT_CAMPUS = Campus.CRES_LLANO_LARGO.value


@dataclass
class TicketPrincipal:
    username: str
    rol: str
    campus: str
    matricula: Optional[str] = None
    nombre: Optional[str] = None
    email: Optional[str] = None
    is_student: bool = False


def get_ticket_repository() -> CosmosTicketRepository:
    global _repository
    if _repository is None:
        _repository = CosmosTicketRepository()
    return _repository


def _authentication_error(detail: str = "Token inválido") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _payload_claim(payload: Dict[str, Any], *names: str) -> Optional[str]:
    for name in names:
        value = payload.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _student_jwt_secret() -> Optional[str]:
    return os.environ.get("STUDENT_JWT_SECRET")


def _student_jwt_algorithm() -> str:
    return os.environ.get("STUDENT_JWT_ALGORITHM", ALGORITHM)


def _safe_claim_keys(payload: Dict[str, Any]) -> List[str]:
    return sorted(str(key) for key in payload.keys())


def _log_jwt_failure(source: str, exc: Exception) -> None:
    logger.warning("Ticket JWT %s validation failed: %s", source, exc.__class__.__name__)


def _log_jwt_success(source: str, payload: Dict[str, Any]) -> None:
    logger.info("Ticket JWT %s validation ok: claims=%s", source, _safe_claim_keys(payload))


def _validate_campus(campus: Optional[str]) -> str:
    value = campus or DEFAULT_STUDENT_CAMPUS
    try:
        return Campus(value).value
    except ValueError:
        raise _authentication_error("Campus inválido")


def _principal_from_token_data(user: TokenData) -> TicketPrincipal:
    return TicketPrincipal(
        username=user.username,
        rol=getattr(user.rol, "value", str(user.rol)),
        campus=getattr(user.campus, "value", str(user.campus)),
    )


def _as_principal(user: Union[TokenData, TicketPrincipal]) -> TicketPrincipal:
    if isinstance(user, TicketPrincipal):
        return user
    return _principal_from_token_data(user)


async def _legacy_get_ticket_principal(token: str = Depends(oauth2_scheme)) -> TicketPrincipal:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise _authentication_error()

    role = _payload_claim(payload, "rol", "role")
    if role == STUDENT_ROLE:
        matricula = _payload_claim(payload, "matricula")
        if not matricula:
            raise _authentication_error("Token de alumno sin matrícula")
        return TicketPrincipal(
            username=f"student:{matricula}",
            rol=STUDENT_ROLE,
            campus=_validate_campus(_payload_claim(payload, "campus")),
            matricula=matricula,
            nombre=_payload_claim(payload, "nombre", "name"),
            email=_payload_claim(payload, "email", "correo"),
            is_student=True,
        )

    username = _payload_claim(payload, "sub")
    campus_claim = _payload_claim(payload, "campus")
    if not username or not role or not campus_claim:
        raise _authentication_error()
    try:
        staff_role = UserRole(role)
        campus = Campus(_validate_campus(campus_claim))
    except ValueError:
        raise _authentication_error()
    return TicketPrincipal(
        username=username,
        rol=staff_role.value,
        campus=campus.value,
    )


def _student_principal_from_payload(
    payload: Dict[str, Any],
    *,
    require_role: bool,
) -> TicketPrincipal:
    role = _payload_claim(payload, "rol", "role")
    if role and role != STUDENT_ROLE:
        raise _authentication_error()
    if require_role and role != STUDENT_ROLE:
        raise _authentication_error()

    matricula = _payload_claim(payload, "matricula")
    if not matricula:
        raise _authentication_error("Token de alumno sin matricula")
    return TicketPrincipal(
        username=f"student:{matricula}",
        rol=STUDENT_ROLE,
        campus=_validate_campus(_payload_claim(payload, "campus")),
        matricula=matricula,
        nombre=_payload_claim(payload, "nombre", "name"),
        email=_payload_claim(payload, "email", "correo"),
        is_student=True,
    )


def _staff_principal_from_payload(payload: Dict[str, Any]) -> TicketPrincipal:
    role = _payload_claim(payload, "rol", "role")
    username = _payload_claim(payload, "sub")
    campus_claim = _payload_claim(payload, "campus")
    if not username or not role or not campus_claim:
        raise _authentication_error()
    try:
        staff_role = UserRole(role)
        campus = Campus(_validate_campus(campus_claim))
    except ValueError:
        raise _authentication_error()
    return TicketPrincipal(
        username=username,
        rol=staff_role.value,
        campus=campus.value,
    )


async def get_ticket_principal(token: str = Depends(oauth2_scheme)) -> TicketPrincipal:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        _log_jwt_success("internal", payload)
        if _payload_claim(payload, "rol", "role") == STUDENT_ROLE:
            return _student_principal_from_payload(payload, require_role=True)
        return _staff_principal_from_payload(payload)
    except JWTError as exc:
        _log_jwt_failure("internal", exc)

    student_secret = _student_jwt_secret()
    if not student_secret:
        logger.warning("Ticket JWT student validation skipped: STUDENT_JWT_SECRET missing")
        raise _authentication_error()

    try:
        payload = jwt.decode(token, student_secret, algorithms=[_student_jwt_algorithm()])
        _log_jwt_success("student", payload)
        return _student_principal_from_payload(payload, require_role=False)
    except JWTError as exc:
        _log_jwt_failure("student", exc)
        raise _authentication_error()


def _campus_value(user: Union[TokenData, TicketPrincipal]) -> str:
    return _as_principal(user).campus


def _role_value(user: Union[TokenData, TicketPrincipal]) -> str:
    return _as_principal(user).rol


def _username_value(user: Union[TokenData, TicketPrincipal]) -> str:
    return _as_principal(user).username


def _student_matricula(user: Union[TokenData, TicketPrincipal]) -> Optional[str]:
    return _as_principal(user).matricula


def _is_student(user: Union[TokenData, TicketPrincipal]) -> bool:
    return _as_principal(user).is_student


def _staff_role(user: Union[TokenData, TicketPrincipal]) -> Optional[UserRole]:
    principal = _as_principal(user)
    if principal.is_student:
        return None
    try:
        return UserRole(principal.rol)
    except ValueError:
        return None


def _require_permission(user: Union[TokenData, TicketPrincipal], permission: str) -> None:
    principal = _as_principal(user)
    if principal.is_student:
        if permission in STUDENT_ALLOWED_PERMISSIONS:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No tienes el permiso: {permission}",
        )

    role = _staff_role(principal)
    if role is None or not has_permission(role, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No tienes el permiso: {permission}",
        )


def _require_internal_ticket_user(user: Union[TokenData, TicketPrincipal], permission: str) -> None:
    if _is_student(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Endpoint disponible solo para usuarios internos SASU",
        )
    _require_permission(user, permission)


def _ensure_same_campus_or_admin(user: Union[TokenData, TicketPrincipal], campus: str) -> None:
    if not _is_student(user):
        return
    role = _staff_role(user)
    if role == UserRole.ADMIN:
        return
    if _campus_value(user) != campus:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a tickets de otro campus",
        )


def _ensure_can_read_ticket(user: Union[TokenData, TicketPrincipal], ticket: Dict[str, Any]) -> None:
    _ensure_same_campus_or_admin(user, ticket.get("campus", ""))
    if _is_student(user):
        if ticket.get("matricula") == _student_matricula(user):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este ticket")

    role = _staff_role(user)
    if role == UserRole.ADMIN or (role is not None and has_permission(role, "tickets:read")):
        return
    username = _username_value(user)
    if ticket.get("createdBy") == username or ticket.get("assignedTo") == username:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este ticket")


def _ensure_can_reply_ticket(user: Union[TokenData, TicketPrincipal], ticket: Dict[str, Any]) -> None:
    _ensure_same_campus_or_admin(user, ticket.get("campus", ""))
    if _is_student(user):
        if ticket.get("matricula") == _student_matricula(user):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes responder este ticket")

    role = _staff_role(user)
    if role == UserRole.ADMIN or (role is not None and has_permission(role, "tickets:reply")):
        return
    if ticket.get("createdBy") == _username_value(user):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes responder este ticket")


def _sender_role_for_user(user: Union[TokenData, TicketPrincipal]) -> str:
    if _is_student(user):
        return TicketSenderRole.ALUMNO.value
    mapping = {
        UserRole.ADMIN: TicketSenderRole.ADMINISTRADOR.value,
        UserRole.MEDICO: TicketSenderRole.MEDICINA.value,
        UserRole.NUTRICION: TicketSenderRole.NUTRICION.value,
        UserRole.PSICOLOGIA: TicketSenderRole.PSICOLOGIA.value,
        UserRole.ENFERMERIA: TicketSenderRole.VACUNACION.value,
        UserRole.SERVICIOS_ESTUDIANTILES: TicketSenderRole.PROMOCION.value,
    }
    return mapping.get(_staff_role(user), TicketSenderRole.ADMINISTRADOR.value)


def _get_ticket_or_404(repository: CosmosTicketRepository, ticket_id: str) -> Dict[str, Any]:
    try:
        return repository.get_ticket(ticket_id)
    except TicketNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket no encontrado")


def _followup_response(followup: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": followup.get("id"),
        "ticket_id": followup.get("ticket_id") or followup.get("ticketId"),
        "author": followup.get("author") or followup.get("senderId"),
        "role": followup.get("role") or followup.get("senderRole"),
        "message": followup.get("message"),
        "visibility": followup.get("visibility") or followup.get("metadata", {}).get("visibility") or "internal",
        "created_at": followup.get("created_at") or followup.get("createdAtUtc"),
        "metadata": followup.get("metadata"),
    }


def _message_visibility(message: Dict[str, Any]) -> Optional[str]:
    metadata = message.get("metadata") or {}
    return message.get("visibility") or metadata.get("visibility")


def _is_student_visible_message(message: Dict[str, Any]) -> bool:
    if message.get("senderRole") == TicketSenderRole.ALUMNO.value:
        return True
    return _message_visibility(message) == "student"


def _filter_messages_for_user(
    user: Union[TokenData, TicketPrincipal],
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not _is_student(user):
        return messages
    return [message for message in messages if _is_student_visible_message(message)]


def _payload_dict(payload, **kwargs) -> Dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(**kwargs)
    return payload.dict(**kwargs)


@router.post("", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    payload: TicketCreate,
    current_user: TicketPrincipal = Depends(get_ticket_principal),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    _require_permission(current_user, "tickets:create")

    now = utc_now_iso()
    ticket = _payload_dict(payload)
    if _is_student(current_user):
        if payload.matricula != _student_matricula(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes crear tickets para otra matrícula",
            )
        ticket["matricula"] = _student_matricula(current_user)
        ticket["patientId"] = ticket.get("patientId") or _student_matricula(current_user)
        if _as_principal(current_user).nombre:
            ticket["nombrePaciente"] = _as_principal(current_user).nombre
        if _as_principal(current_user).email:
            ticket["email"] = _as_principal(current_user).email
        ticket["campus"] = _campus_value(current_user)
    else:
        _ensure_same_campus_or_admin(current_user, payload.campus)

    ticket.update(
        {
            "id": generate_ticket_id(),
            "ticketNumber": generate_ticket_number(),
            "estado": TicketEstado.ABIERTO.value,
            "createdAtUtc": now,
            "updatedAtUtc": now,
            "closedAtUtc": None,
            "createdBy": _username_value(current_user),
            "createdByRole": _role_value(current_user),
            "lastMessageAtUtc": now,
            "lastMessagePreview": payload.descripcionInicial[:120],
            "deleted": False,
            "schemaVersion": 1,
        }
    )
    return repository.create_ticket(ticket)


@router.get("", response_model=List[TicketResponse])
async def list_tickets(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    category: Optional[str] = None,
    priority: Optional[str] = None,
    campus: Optional[str] = None,
    unidad_academica: Optional[str] = None,
    preparatoria: Optional[str] = None,
    student_id: Optional[str] = None,
    matricula: Optional[str] = None,
    current_user: TicketPrincipal = Depends(get_ticket_principal),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    _require_internal_ticket_user(current_user, "tickets:read")
    return repository.list_tickets(
        {
            "status": status_filter,
            "category": category,
            "priority": priority,
            "campus": campus,
            "unidad_academica": unidad_academica,
            "preparatoria": preparatoria,
            "student_id": student_id,
            "matricula": matricula,
        }
    )


@router.get("/my", response_model=List[TicketResponse])
async def get_my_tickets(
    current_user: TicketPrincipal = Depends(get_ticket_principal),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    _require_permission(current_user, "tickets:read")
    if _is_student(current_user):
        return repository.list_student_tickets(
            matricula=_student_matricula(current_user),
            campus=_campus_value(current_user),
        )

    role = _staff_role(current_user)
    include_campus_queue = role == UserRole.ADMIN or (role is not None and has_permission(role, "tickets:manage"))
    return repository.list_my_tickets(
        username=_username_value(current_user),
        campus=_campus_value(current_user),
        include_campus_queue=include_campus_queue,
    )


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket_detail(
    ticket_id: str,
    current_user: TicketPrincipal = Depends(get_ticket_principal),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    _require_internal_ticket_user(current_user, "tickets:read")
    ticket = _get_ticket_or_404(repository, ticket_id)
    _ensure_can_read_ticket(current_user, ticket)
    messages = repository.list_messages(ticket_id)
    followups = [_followup_response(item) for item in repository.list_followups(ticket_id)]
    return {"ticket": ticket, "messages": messages, "followups": followups}


@router.post("/{ticket_id}/messages", response_model=TicketMessageResponse, status_code=status.HTTP_201_CREATED)
async def add_ticket_message(
    ticket_id: str,
    payload: TicketMessageCreate,
    current_user: TicketPrincipal = Depends(get_ticket_principal),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    ticket = _get_ticket_or_404(repository, ticket_id)
    _ensure_can_reply_ticket(current_user, ticket)

    now = utc_now_iso()
    message = {
        "id": generate_ticket_message_id(),
        "ticketId": ticket_id,
        "senderId": _username_value(current_user),
        "senderRole": _sender_role_for_user(current_user),
        "senderName": _as_principal(current_user).nombre or _username_value(current_user),
        "message": payload.message,
        "createdAtUtc": now,
        "readAtUtc": None,
        "attachmentUrl": payload.attachmentUrl,
        "deleted": False,
    }
    created = repository.add_message(ticket_id, message)

    if ticket.get("estado") in (TicketEstado.ABIERTO.value, TicketEstado.PENDIENTE_PACIENTE.value):
        repository.update_ticket(ticket_id, {"estado": TicketEstado.EN_ATENCION.value, "updatedAtUtc": now})

    return created


@router.get("/{ticket_id}/messages", response_model=List[TicketMessageResponse])
async def get_ticket_messages(
    ticket_id: str,
    current_user: TicketPrincipal = Depends(get_ticket_principal),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    ticket = _get_ticket_or_404(repository, ticket_id)
    _ensure_can_read_ticket(current_user, ticket)
    return _filter_messages_for_user(current_user, repository.list_messages(ticket_id))


@router.patch("/{ticket_id}/assign", response_model=TicketResponse)
async def assign_ticket(
    ticket_id: str,
    payload: TicketAssignUpdate,
    current_user: TicketPrincipal = Depends(get_ticket_principal),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    _require_permission(current_user, "tickets:assign")
    ticket = _get_ticket_or_404(repository, ticket_id)
    _ensure_same_campus_or_admin(current_user, ticket.get("campus", ""))

    updates = _payload_dict(payload, exclude_unset=True)
    updates["estado"] = TicketEstado.ASIGNADO.value
    updates["updatedAtUtc"] = utc_now_iso()
    return repository.update_ticket(ticket_id, updates)


@router.patch("/{ticket_id}/status", response_model=TicketResponse)
async def update_ticket_status(
    ticket_id: str,
    payload: TicketStatusUpdate,
    current_user: TicketPrincipal = Depends(get_ticket_principal),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    _require_internal_ticket_user(current_user, "tickets:update_status")
    ticket = _get_ticket_or_404(repository, ticket_id)

    now = utc_now_iso()
    previous_status = ticket.get("estado")
    status_history = list(ticket.get("statusHistory") or [])
    status_history.append(
        {
            "previousStatus": previous_status,
            "newStatus": payload.estado,
            "changedBy": _username_value(current_user),
            "changedByRole": _role_value(current_user),
            "changedAtUtc": now,
        }
    )
    updates = {
        "estado": payload.estado,
        "updatedAtUtc": now,
        "statusHistory": status_history,
    }
    if payload.estado == TicketEstado.CERRADO.value:
        updates["closedAtUtc"] = now
        updates["closedBy"] = _username_value(current_user)
    elif ticket.get("closedAtUtc") and payload.estado != TicketEstado.CERRADO.value:
        updates["closedAtUtc"] = None
        updates["closedBy"] = None
    return repository.update_ticket(ticket_id, updates)


@router.post("/{ticket_id}/followups", response_model=TicketFollowupResponse, status_code=status.HTTP_201_CREATED)
async def add_ticket_followup(
    ticket_id: str,
    payload: TicketFollowupCreate,
    current_user: TicketPrincipal = Depends(get_ticket_principal),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    _require_internal_ticket_user(current_user, "tickets:reply")
    _get_ticket_or_404(repository, ticket_id)

    now = utc_now_iso()
    followup = {
        "id": generate_ticket_message_id(),
        "ticketId": ticket_id,
        "ticket_id": ticket_id,
        "senderId": _username_value(current_user),
        "senderRole": _sender_role_for_user(current_user),
        "senderName": _as_principal(current_user).nombre or _username_value(current_user),
        "author": _username_value(current_user),
        "role": _role_value(current_user),
        "message": payload.message,
        "visibility": payload.visibility,
        "createdAtUtc": now,
        "created_at": now,
        "readAtUtc": None,
        "attachmentUrl": None,
        "deleted": False,
        "metadata": {
            "messageType": "followup",
            "visibility": payload.visibility,
        },
    }
    return _followup_response(repository.add_followup(ticket_id, followup))


@router.patch("/{ticket_id}/appointment", response_model=TicketResponse)
async def update_ticket_appointment(
    ticket_id: str,
    payload: TicketAppointmentUpdate,
    current_user: TicketPrincipal = Depends(get_ticket_principal),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    _require_permission(current_user, "tickets:update_status")
    ticket = _get_ticket_or_404(repository, ticket_id)
    _ensure_same_campus_or_admin(current_user, ticket.get("campus", ""))

    return repository.update_ticket(
        ticket_id,
        {
            "appointmentMode": payload.appointmentMode,
            "appointmentAtUtc": payload.appointmentAtUtc,
            "updatedAtUtc": utc_now_iso(),
        },
    )


@router.patch("/{ticket_id}/videocall", response_model=TicketResponse)
async def update_ticket_videocall(
    ticket_id: str,
    payload: TicketVideoCallUpdate,
    current_user: TicketPrincipal = Depends(get_ticket_principal),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    _require_permission(current_user, "tickets:update_status")
    ticket = _get_ticket_or_404(repository, ticket_id)
    _ensure_same_campus_or_admin(current_user, ticket.get("campus", ""))

    return repository.update_ticket(
        ticket_id,
        {
            "videoCallUrl": payload.videoCallUrl,
            "updatedAtUtc": utc_now_iso(),
        },
    )
