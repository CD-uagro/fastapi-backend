"""Restablecimiento asistido, exclusivo de administradores autenticados."""
from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from auth_models import AuditAction, UserRole
from auth_service import AuthService, require_role


class AdminPasswordReset(BaseModel):
    password: str = Field(..., min_length=8, max_length=72)
    identity_verified: bool


def build_admin_reset_router(users, audit):
    router = APIRouter()

    @router.post("/auth/users/{user_id}/reset-password", tags=["Gestión de Usuarios"])
    def reset_password(user_id: str, payload: AdminPasswordReset,
                       current_user=Depends(require_role(UserRole.ADMIN))):
        if not payload.identity_verified:
            raise HTTPException(400, "Verifica la identidad de la persona antes de restablecer su contraseña.")
        valid, reason = AuthService.validate_password_strength(payload.password)
        if not valid or len(payload.password.encode("utf-8")) > 72:
            raise HTTPException(400, reason if not valid else "La contraseña supera 72 bytes.")
        try:
            doc = users.read_item(user_id, user_id)
            if not user_id.startswith("user:") or doc.get("type", "user") != "user":
                raise HTTPException(404, "Usuario no encontrado.")
            if not doc.get("activo"):
                raise HTTPException(400, "La cuenta está inactiva. Revisa su estado antes de restablecer el acceso.")
            updated = {k: v for k, v in doc.items() if not k.startswith("_")}
            updated.pop("password_recovery", None)
            updated.update(password_hash=AuthService.hash_password(payload.password),
                           intentos_fallidos=0, bloqueado_hasta=None)
            users.container.replace_item(user_id, updated, etag=doc["_etag"],
                                         match_condition=MatchConditions.IfNotModified)
        except CosmosHttpResponseError as exc:
            if exc.status_code == 404:
                raise HTTPException(404, "Usuario no encontrado.") from None
            if exc.status_code == 412:
                raise HTTPException(409, "La cuenta cambió durante la operación. Actualiza la lista y vuelve a intentar.") from None
            raise HTTPException(503, "No se pudo guardar el cambio. Intenta de nuevo.") from None
        audit(current_user.username, AuditAction.UPDATE_USER, user_id,
              "Restablecimiento de contraseña por administrador; identidad verificada.")
        return {"message": "Contraseña restablecida. La persona ya puede iniciar sesión en la app con su nueva contraseña."}

    return router
