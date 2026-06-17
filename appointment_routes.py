from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from appointment_models import (
    AppointmentCancelUpdate,
    AppointmentResponse,
    AppointmentRescheduleUpdate,
    AppointmentScheduleUpdate,
    AppointmentSimpleStatusUpdate,
    AppointmentStatus,
    FINAL_APPOINTMENT_STATUSES,
    utc_now_iso,
)
from appointment_repository import (
    AppointmentNotFoundError,
    CosmosAppointmentRepository,
)
from auth_models import TokenData, has_permission
from auth_service import get_current_user


router = APIRouter(prefix="/appointments", tags=["appointments"])

_repository = None


def get_appointment_repository() -> CosmosAppointmentRepository:
    global _repository
    if _repository is None:
        _repository = CosmosAppointmentRepository()
    return _repository


def _require_internal_permission(user: TokenData, permission: str) -> None:
    if not has_permission(user.rol, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No tienes el permiso: {permission}",
        )


def _get_appointment_or_404(
    repository: CosmosAppointmentRepository,
    appointment_id: str,
) -> Dict[str, Any]:
    try:
        return repository.get_appointment(appointment_id)
    except AppointmentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cita no encontrada")


def _history_entry(
    *,
    previous_status: Optional[str],
    new_status: str,
    user: TokenData,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "from": previous_status,
        "to": new_status,
        "actor": user.username,
        "actor_role": user.rol.value,
        "message": message,
        "created_at": utc_now_iso(),
    }


def _update_status(
    *,
    repository: CosmosAppointmentRepository,
    appointment: Dict[str, Any],
    new_status: AppointmentStatus,
    user: TokenData,
    updates: Optional[Dict[str, Any]] = None,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    previous_status = appointment.get("status")
    if previous_status in FINAL_APPOINTMENT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La cita ya esta cerrada y no permite cambios",
        )

    now = utc_now_iso()
    history = list(appointment.get("history") or [])
    history.append(
        _history_entry(
            previous_status=previous_status,
            new_status=new_status.value,
            user=user,
            message=message,
        )
    )
    payload = {
        "status": new_status.value,
        "history": history,
        "updated_at": now,
        "updated_by": user.username,
    }
    if updates:
        payload.update(updates)
    return repository.update_appointment(appointment["id"], payload)


@router.get("", response_model=list[AppointmentResponse])
async def list_appointments(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    area: Optional[str] = None,
    priority: Optional[str] = None,
    campus: Optional[str] = None,
    matricula: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosAppointmentRepository = Depends(get_appointment_repository),
):
    _require_internal_permission(current_user, "citas:read")
    return repository.list_appointments(
        {
            "status": status_filter,
            "area": area,
            "priority": priority,
            "campus": campus,
            "matricula": matricula,
        }
    )


@router.get("/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment_detail(
    appointment_id: str,
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosAppointmentRepository = Depends(get_appointment_repository),
):
    _require_internal_permission(current_user, "citas:read")
    return _get_appointment_or_404(repository, appointment_id)


@router.patch("/{appointment_id}/confirm", response_model=AppointmentResponse)
async def confirm_appointment(
    appointment_id: str,
    payload: AppointmentScheduleUpdate,
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosAppointmentRepository = Depends(get_appointment_repository),
):
    _require_internal_permission(current_user, "citas:update")
    appointment = _get_appointment_or_404(repository, appointment_id)
    return _update_status(
        repository=repository,
        appointment=appointment,
        new_status=AppointmentStatus.CONFIRMED,
        user=current_user,
        updates={
            "scheduled_start": payload.scheduled_start,
            "scheduled_end": payload.scheduled_end,
            "assigned_to": payload.assigned_to,
        },
        message=payload.message or "Cita confirmada por SASU",
    )


@router.patch("/{appointment_id}/reschedule", response_model=AppointmentResponse)
async def reschedule_appointment(
    appointment_id: str,
    payload: AppointmentRescheduleUpdate,
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosAppointmentRepository = Depends(get_appointment_repository),
):
    _require_internal_permission(current_user, "citas:update")
    appointment = _get_appointment_or_404(repository, appointment_id)
    return _update_status(
        repository=repository,
        appointment=appointment,
        new_status=AppointmentStatus.RESCHEDULED,
        user=current_user,
        updates={
            "scheduled_start": payload.scheduled_start,
            "scheduled_end": payload.scheduled_end,
            "assigned_to": payload.assigned_to,
            "reschedule_reason": payload.reschedule_reason,
        },
        message=payload.message or payload.reschedule_reason or "Cita reprogramada por SASU",
    )


@router.patch("/{appointment_id}/cancel", response_model=AppointmentResponse)
async def cancel_appointment(
    appointment_id: str,
    payload: AppointmentCancelUpdate,
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosAppointmentRepository = Depends(get_appointment_repository),
):
    _require_internal_permission(current_user, "citas:update")
    appointment = _get_appointment_or_404(repository, appointment_id)
    return _update_status(
        repository=repository,
        appointment=appointment,
        new_status=AppointmentStatus.CANCELLED_BY_STAFF,
        user=current_user,
        updates={"cancellation_reason": payload.cancellation_reason},
        message=payload.cancellation_reason or "Cita cancelada por SASU",
    )


@router.patch("/{appointment_id}/attended", response_model=AppointmentResponse)
async def mark_appointment_attended(
    appointment_id: str,
    payload: AppointmentSimpleStatusUpdate = AppointmentSimpleStatusUpdate(),
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosAppointmentRepository = Depends(get_appointment_repository),
):
    _require_internal_permission(current_user, "citas:update")
    appointment = _get_appointment_or_404(repository, appointment_id)
    return _update_status(
        repository=repository,
        appointment=appointment,
        new_status=AppointmentStatus.ATTENDED,
        user=current_user,
        message=payload.message or "Cita marcada como atendida",
    )


@router.patch("/{appointment_id}/no-show", response_model=AppointmentResponse)
async def mark_appointment_no_show(
    appointment_id: str,
    payload: AppointmentSimpleStatusUpdate = AppointmentSimpleStatusUpdate(),
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosAppointmentRepository = Depends(get_appointment_repository),
):
    _require_internal_permission(current_user, "citas:update")
    appointment = _get_appointment_or_404(repository, appointment_id)
    return _update_status(
        repository=repository,
        appointment=appointment,
        new_status=AppointmentStatus.NO_SHOW,
        user=current_user,
        message=payload.message or "El alumno no asistio a la cita",
    )
