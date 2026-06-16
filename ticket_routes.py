from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status

from auth_models import TokenData, UserRole, has_permission
from auth_service import get_current_user
from ticket_models import (
    TicketAppointmentUpdate,
    TicketAssignUpdate,
    TicketCreate,
    TicketDetailResponse,
    TicketEstado,
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

_repository = None


def get_ticket_repository() -> CosmosTicketRepository:
    global _repository
    if _repository is None:
        _repository = CosmosTicketRepository()
    return _repository


def _campus_value(user: TokenData) -> str:
    return getattr(user.campus, "value", str(user.campus))


def _role_value(user: TokenData) -> str:
    return getattr(user.rol, "value", str(user.rol))


def _require_permission(user: TokenData, permission: str) -> None:
    if not has_permission(user.rol, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No tienes el permiso: {permission}",
        )


def _ensure_same_campus_or_admin(user: TokenData, campus: str) -> None:
    if user.rol == UserRole.ADMIN:
        return
    if _campus_value(user) != campus:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a tickets de otro campus",
        )


def _ensure_can_read_ticket(user: TokenData, ticket: Dict[str, Any]) -> None:
    _ensure_same_campus_or_admin(user, ticket.get("campus", ""))
    if user.rol == UserRole.ADMIN or has_permission(user.rol, "tickets:read"):
        return
    if ticket.get("createdBy") == user.username or ticket.get("assignedTo") == user.username:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este ticket")


def _ensure_can_reply_ticket(user: TokenData, ticket: Dict[str, Any]) -> None:
    _ensure_same_campus_or_admin(user, ticket.get("campus", ""))
    if user.rol == UserRole.ADMIN or has_permission(user.rol, "tickets:reply"):
        return
    if ticket.get("createdBy") == user.username:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes responder este ticket")


def _sender_role_for_user(user: TokenData) -> str:
    mapping = {
        UserRole.ADMIN: TicketSenderRole.ADMINISTRADOR.value,
        UserRole.MEDICO: TicketSenderRole.MEDICINA.value,
        UserRole.NUTRICION: TicketSenderRole.NUTRICION.value,
        UserRole.PSICOLOGIA: TicketSenderRole.PSICOLOGIA.value,
        UserRole.ENFERMERIA: TicketSenderRole.VACUNACION.value,
        UserRole.SERVICIOS_ESTUDIANTILES: TicketSenderRole.PROMOCION.value,
    }
    return mapping.get(user.rol, TicketSenderRole.ADMINISTRADOR.value)


def _get_ticket_or_404(repository: CosmosTicketRepository, ticket_id: str) -> Dict[str, Any]:
    try:
        return repository.get_ticket(ticket_id)
    except TicketNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket no encontrado")


def _payload_dict(payload, **kwargs) -> Dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(**kwargs)
    return payload.dict(**kwargs)


@router.post("", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    payload: TicketCreate,
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    _require_permission(current_user, "tickets:create")
    _ensure_same_campus_or_admin(current_user, payload.campus)

    now = utc_now_iso()
    ticket = _payload_dict(payload)
    ticket.update(
        {
            "id": generate_ticket_id(),
            "ticketNumber": generate_ticket_number(),
            "estado": TicketEstado.ABIERTO.value,
            "createdAtUtc": now,
            "updatedAtUtc": now,
            "closedAtUtc": None,
            "createdBy": current_user.username,
            "createdByRole": _role_value(current_user),
            "lastMessageAtUtc": now,
            "lastMessagePreview": payload.descripcionInicial[:120],
            "deleted": False,
            "schemaVersion": 1,
        }
    )
    return repository.create_ticket(ticket)


@router.get("/my", response_model=List[TicketResponse])
async def get_my_tickets(
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    _require_permission(current_user, "tickets:read")
    include_campus_queue = current_user.rol == UserRole.ADMIN or has_permission(current_user.rol, "tickets:manage")
    return repository.list_my_tickets(
        username=current_user.username,
        campus=_campus_value(current_user),
        include_campus_queue=include_campus_queue,
    )


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket_detail(
    ticket_id: str,
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    ticket = _get_ticket_or_404(repository, ticket_id)
    _ensure_can_read_ticket(current_user, ticket)
    messages = repository.list_messages(ticket_id)
    return {"ticket": ticket, "messages": messages}


@router.post("/{ticket_id}/messages", response_model=TicketMessageResponse, status_code=status.HTTP_201_CREATED)
async def add_ticket_message(
    ticket_id: str,
    payload: TicketMessageCreate,
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    ticket = _get_ticket_or_404(repository, ticket_id)
    _ensure_can_reply_ticket(current_user, ticket)

    now = utc_now_iso()
    message = {
        "id": generate_ticket_message_id(),
        "ticketId": ticket_id,
        "senderId": current_user.username,
        "senderRole": _sender_role_for_user(current_user),
        "senderName": current_user.username,
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
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    ticket = _get_ticket_or_404(repository, ticket_id)
    _ensure_can_read_ticket(current_user, ticket)
    return repository.list_messages(ticket_id)


@router.patch("/{ticket_id}/assign", response_model=TicketResponse)
async def assign_ticket(
    ticket_id: str,
    payload: TicketAssignUpdate,
    current_user: TokenData = Depends(get_current_user),
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
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosTicketRepository = Depends(get_ticket_repository),
):
    _require_permission(current_user, "tickets:update_status")
    ticket = _get_ticket_or_404(repository, ticket_id)
    _ensure_same_campus_or_admin(current_user, ticket.get("campus", ""))

    now = utc_now_iso()
    updates = {"estado": payload.estado, "updatedAtUtc": now}
    if payload.estado == TicketEstado.CERRADO.value:
        updates["closedAtUtc"] = now
        updates["closedBy"] = current_user.username
    elif ticket.get("closedAtUtc") and payload.estado != TicketEstado.CERRADO.value:
        updates["closedAtUtc"] = None
        updates["closedBy"] = None
    return repository.update_ticket(ticket_id, updates)


@router.patch("/{ticket_id}/appointment", response_model=TicketResponse)
async def update_ticket_appointment(
    ticket_id: str,
    payload: TicketAppointmentUpdate,
    current_user: TokenData = Depends(get_current_user),
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
    current_user: TokenData = Depends(get_current_user),
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
