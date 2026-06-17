from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth_models import TokenData, UserRole
from auth_service import get_current_user
from referral_models import (
    CounterReferral,
    CounterReferralCreate,
    FINAL_REFERRAL_STATUSES,
    Referral,
    ReferralArea,
    ReferralCreate,
    ReferralStatus,
    ReferralUpdateStatus,
    VALID_REFERRAL_TRANSITIONS,
    utc_now_iso,
)
from referral_repository import (
    CosmosReferralRepository,
    ReferralNotFoundError,
    generate_referral_id,
)


router = APIRouter(tags=["referrals"])

_repository = None


ROLE_AREA_MAP = {
    UserRole.MEDICO: ReferralArea.MEDICO.value,
    UserRole.PSICOLOGIA: ReferralArea.PSICOLOGIA.value,
    UserRole.NUTRICION: ReferralArea.NUTRICION.value,
    UserRole.ODONTOLOGIA: ReferralArea.ODONTOLOGIA.value,
    UserRole.SERVICIOS_ESTUDIANTILES: ReferralArea.ATENCION_ESTUDIANTIL.value,
}


def get_referral_repository() -> CosmosReferralRepository:
    global _repository
    if _repository is None:
        _repository = CosmosReferralRepository()
    return _repository


def _payload_dict(payload, **kwargs) -> Dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(**kwargs)
    return payload.dict(**kwargs)


def _role_value(user: TokenData) -> str:
    return getattr(user.rol, "value", str(user.rol))


def _user_area(user: TokenData) -> Optional[str]:
    return ROLE_AREA_MAP.get(user.rol)


def _is_admin(user: TokenData) -> bool:
    return user.rol == UserRole.ADMIN


def _require_internal_referral_user(user: TokenData) -> None:
    if user.rol not in set(ROLE_AREA_MAP.keys()) | {UserRole.ADMIN}:
        # TODO SASU 2.7.0: si se agregan permisos "referrals:*" en auth_models,
        # sustituir esta regla local por has_permission().
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Endpoint disponible solo para usuarios internos SASU autorizados",
        )


def _ensure_can_create_for_origin(user: TokenData, origin_area: str) -> None:
    _require_internal_referral_user(user)
    if _is_admin(user):
        return
    if _user_area(user) != origin_area:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes crear referencias desde otra area",
        )


def _ensure_can_read_referral(user: TokenData, referral: Dict[str, Any]) -> None:
    _require_internal_referral_user(user)
    if _is_admin(user):
        return
    area = _user_area(user)
    if area and (
        (referral.get("origin") or {}).get("area") == area
        or (referral.get("destination") or {}).get("area") == area
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No tienes acceso a esta referencia",
    )


def _ensure_can_change_status(user: TokenData, referral: Dict[str, Any], new_status: str) -> None:
    _ensure_can_read_referral(user, referral)
    if _is_admin(user):
        return

    area = _user_area(user)
    origin_area = (referral.get("origin") or {}).get("area")
    destination_area = (referral.get("destination") or {}).get("area")

    if new_status == ReferralStatus.SENT.value and area == origin_area:
        return
    if new_status in {
        ReferralStatus.RECEIVED.value,
        ReferralStatus.ACCEPTED.value,
        ReferralStatus.SCHEDULED.value,
        ReferralStatus.ATTENDED.value,
    } and area == destination_area:
        return
    if new_status == ReferralStatus.CLOSED.value and area in {origin_area, destination_area}:
        return
    if new_status == ReferralStatus.CANCELLED.value and area in {origin_area, destination_area}:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No tienes permiso para realizar esta transicion",
    )


def _ensure_can_counter_refer(user: TokenData, referral: Dict[str, Any]) -> None:
    _ensure_can_read_referral(user, referral)
    if _is_admin(user):
        return
    if _user_area(user) == (referral.get("destination") or {}).get("area"):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Solo el area destino puede registrar contrarreferencia",
    )


def _get_referral_or_404(repository: CosmosReferralRepository, referral_id: str) -> Dict[str, Any]:
    try:
        return repository.get_referral(referral_id)
    except ReferralNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Referencia no encontrada")


def _history_entry(
    *,
    previous_status: Optional[str],
    new_status: str,
    user: TokenData,
    note: Optional[str] = None,
    appointment_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "previousStatus": previous_status,
        "status": new_status,
        "at": utc_now_iso(),
        "byUserId": user.username,
        "byUserName": user.username,
        "byRole": _role_value(user),
        "area": _user_area(user),
        "note": note,
        "appointmentId": appointment_id,
        "metadata": metadata,
    }


def _status_timestamp_field(new_status: str) -> Optional[str]:
    return {
        ReferralStatus.RECEIVED.value: "receivedAt",
        ReferralStatus.ACCEPTED.value: "acceptedAt",
        ReferralStatus.SCHEDULED.value: "scheduledAt",
        ReferralStatus.ATTENDED.value: "attendedAt",
        ReferralStatus.CLOSED.value: "closedAt",
        ReferralStatus.CANCELLED.value: "cancelledAt",
    }.get(new_status)


def _validate_transition(current_status: str, new_status: str) -> None:
    allowed = VALID_REFERRAL_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transicion invalida: {current_status} -> {new_status}",
        )


@router.post("/referrals", response_model=Referral, status_code=status.HTTP_201_CREATED)
async def create_referral(
    payload: ReferralCreate,
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosReferralRepository = Depends(get_referral_repository),
):
    _ensure_can_create_for_origin(current_user, payload.originArea)

    now = utc_now_iso()
    initial_status = ReferralStatus.SENT.value if payload.send else ReferralStatus.DRAFT.value
    referral_id = generate_referral_id()
    referral = {
        "id": referral_id,
        "type": "referral",
        "student": _payload_dict(payload.student),
        "origin": {
            "area": payload.originArea,
            "userId": current_user.username,
            "userName": current_user.username,
            "role": _role_value(current_user),
        },
        "destination": {
            "area": payload.destinationArea,
            "assignedUserId": None,
            "assignedUserName": None,
        },
        "priority": payload.priority,
        "reason": payload.reason,
        "observations": payload.observations,
        "status": initial_status,
        "createdAt": now,
        "updatedAt": now,
        "receivedAt": None,
        "acceptedAt": None,
        "scheduledAt": None,
        "attendedAt": None,
        "closedAt": None,
        "cancelledAt": None,
        "cancellationReason": None,
        "appointmentId": None,
        "counterReferral": None,
        "statusHistory": [
            _history_entry(
                previous_status=None,
                new_status=initial_status,
                user=current_user,
                note="Referencia enviada" if payload.send else "Referencia creada como borrador",
            )
        ],
        "createdBy": current_user.username,
        "createdByRole": _role_value(current_user),
        "updatedBy": current_user.username,
        "updatedByRole": _role_value(current_user),
        "schemaVersion": 1,
    }
    return repository.create_referral(referral)


@router.get("/referrals", response_model=List[Referral])
async def list_referrals(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    priority: Optional[str] = None,
    origin_area: Optional[str] = None,
    destination_area: Optional[str] = None,
    matricula: Optional[str] = None,
    student_name: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosReferralRepository = Depends(get_referral_repository),
):
    _require_internal_referral_user(current_user)
    referrals = repository.list_referrals(
        {
            "status": status_filter,
            "priority": priority,
            "origin_area": origin_area,
            "destination_area": destination_area,
            "matricula": matricula,
            "student_name": student_name,
        }
    )
    if _is_admin(current_user):
        return referrals

    area = _user_area(current_user)
    return [
        referral
        for referral in referrals
        if (referral.get("origin") or {}).get("area") == area
        or (referral.get("destination") or {}).get("area") == area
    ]


@router.get("/referrals/pending", response_model=List[Referral])
async def list_pending_referrals(
    area: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosReferralRepository = Depends(get_referral_repository),
):
    _require_internal_referral_user(current_user)
    if not _is_admin(current_user):
        area = _user_area(current_user)
    return repository.list_pending_referrals(area=area)


@router.get("/referrals/{referral_id}", response_model=Referral)
async def get_referral_detail(
    referral_id: str,
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosReferralRepository = Depends(get_referral_repository),
):
    referral = _get_referral_or_404(repository, referral_id)
    _ensure_can_read_referral(current_user, referral)
    return referral


@router.patch("/referrals/{referral_id}/status", response_model=Referral)
async def update_referral_status(
    referral_id: str,
    payload: ReferralUpdateStatus,
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosReferralRepository = Depends(get_referral_repository),
):
    referral = _get_referral_or_404(repository, referral_id)
    previous_status = referral.get("status")
    new_status = payload.status

    _validate_transition(previous_status, new_status)
    _ensure_can_change_status(current_user, referral, new_status)

    now = utc_now_iso()
    status_history = list(referral.get("statusHistory") or [])
    status_history.append(
        _history_entry(
            previous_status=previous_status,
            new_status=new_status,
            user=current_user,
            note=payload.note or payload.reason,
            appointment_id=payload.appointmentId,
        )
    )

    updates = {
        "status": new_status,
        "statusHistory": status_history,
        "updatedAt": now,
        "updatedBy": current_user.username,
        "updatedByRole": _role_value(current_user),
    }
    timestamp_field = _status_timestamp_field(new_status)
    if timestamp_field:
        updates[timestamp_field] = now
    if new_status == ReferralStatus.SCHEDULED.value and payload.appointmentId:
        updates["appointmentId"] = payload.appointmentId
    if new_status == ReferralStatus.CANCELLED.value:
        updates["cancellationReason"] = payload.reason or payload.note

    return repository.update_referral(referral_id, updates)


@router.post("/referrals/{referral_id}/counter-referral", response_model=Referral, status_code=status.HTTP_201_CREATED)
async def add_counter_referral(
    referral_id: str,
    payload: CounterReferralCreate,
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosReferralRepository = Depends(get_referral_repository),
):
    referral = _get_referral_or_404(repository, referral_id)
    _ensure_can_counter_refer(current_user, referral)

    if referral.get("status") in FINAL_REFERRAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede registrar contrarreferencia en una referencia cerrada o cancelada",
        )

    now = utc_now_iso()
    counter_referral = CounterReferral(
        responseArea=_user_area(current_user) or (referral.get("destination") or {}).get("area"),
        responseUserId=current_user.username,
        responseUserName=current_user.username,
        responseRole=_role_value(current_user),
        summary=payload.summary,
        recommendations=payload.recommendations,
        followUpRequired=payload.followUpRequired,
        followUpArea=payload.followUpArea,
        nextSuggestedAction=payload.nextSuggestedAction,
        createdAt=now,
    )

    status_history = list(referral.get("statusHistory") or [])
    status_history.append(
        _history_entry(
            previous_status=referral.get("status"),
            new_status=referral.get("status"),
            user=current_user,
            note="Contrarreferencia registrada",
            metadata={"event": "counter_referral_created"},
        )
    )

    return repository.update_referral(
        referral_id,
        {
            "counterReferral": _payload_dict(counter_referral),
            "statusHistory": status_history,
            "updatedAt": now,
            "updatedBy": current_user.username,
            "updatedByRole": _role_value(current_user),
        },
    )


@router.get("/students/{matricula}/referrals", response_model=List[Referral])
async def list_student_referrals(
    matricula: str,
    current_user: TokenData = Depends(get_current_user),
    repository: CosmosReferralRepository = Depends(get_referral_repository),
):
    _require_internal_referral_user(current_user)
    referrals = repository.list_student_referrals(matricula)
    if _is_admin(current_user):
        return referrals

    area = _user_area(current_user)
    return [
        referral
        for referral in referrals
        if (referral.get("origin") or {}).get("area") == area
        or (referral.get("destination") or {}).get("area") == area
    ]
