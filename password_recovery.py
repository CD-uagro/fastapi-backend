"""Recuperación aislada: tokens aleatorios, límites persistentes y consumo atómico."""
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from auth_models import Campus
from auth_service import AuthService

logger = logging.getLogger(__name__)
GENERIC = "Si los datos coinciden con una cuenta activa, recibirás un enlace en tu correo. Revisa también la carpeta de correo no deseado."
INVALID = "El enlace no es válido, ya se usó o venció. Solicita uno nuevo."


class RecoveryRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    campus: Campus
    email: EmailStr


class RecoveryConfirmation(BaseModel):
    token: str = Field(..., min_length=40, max_length=500)
    password: str = Field(..., min_length=8, max_length=72)


def mail_config():
    origin = os.environ.get("PASSWORD_RESET_BASE_URL", "https://fastapi-backend-o7ks.onrender.com").rstrip("/")
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        return None
    key, sender = os.environ.get("RESEND_API_KEY"), os.environ.get("PASSWORD_RESET_FROM")
    if os.environ.get("PASSWORD_RESET_ENABLED", "false").lower() != "true" or not key or not sender:
        return None
    return {"origin": origin, "key": key, "sender": sender}


def send_email(config, email, username, link, digest):
    body = json.dumps({
        "from": config["sender"], "to": [email], "subject": "SASU: restablecer tu contraseña",
        "text": f"Recibimos una solicitud para restablecer el acceso de {username}.\n\nAbre este enlace dentro de 15 minutos:\n{link}\n\nSolo puede utilizarse una vez. Si no lo solicitaste, ignora este correo; tu contraseña no ha cambiado.",
    }).encode("utf-8")
    req = urllib.request.Request("https://api.resend.com/emails", data=body, method="POST", headers={
        "Authorization": "Bearer " + config["key"], "Content-Type": "application/json",
        "User-Agent": "SASU-password-recovery/1", "Idempotency-Key": "password-reset/" + digest,
    })
    with urllib.request.urlopen(req, timeout=10) as response:
        # Nunca registrar enlaces, claves, contraseñas ni la respuesta del proveedor.
        if response.status not in (200, 201, 202):
            raise RuntimeError("mail_failed")


class RecoveryService:
    def __init__(self, users, audit, sender=send_email, clock=time.time):
        self.users, self.audit, self.sender, self.clock = users, audit, sender, clock

    def replace(self, doc, **changes):
        updated = {k: v for k, v in doc.items() if not k.startswith("_")}
        updated.update(changes)
        return self.users.container.replace_item(doc["id"], updated, etag=doc["_etag"],
                                                 match_condition=MatchConditions.IfNotModified)

    def limit(self, key, maximum):
        # Un registro por IP (hash), sin guardar la dirección ni crear contenedores.
        item_id = "reset-rate:" + hashlib.sha256(key.encode()).hexdigest()
        for _ in range(4):
            try:
                doc = self.users.read_item(item_id, item_id)
            except CosmosHttpResponseError as exc:
                if exc.status_code != 404:
                    raise
                try:
                    self.users.create_item({"id": item_id, "count": 1, "expires": self.clock() + 900})
                    return
                except CosmosHttpResponseError as collision:
                    if collision.status_code == 409:
                        continue
                    raise
            expired = doc["expires"] <= self.clock()
            if not expired and doc["count"] >= maximum:
                raise HTTPException(429, "Espera unos minutos antes de volver a intentar.")
            try:
                self.replace(doc, count=1 if expired else doc["count"] + 1,
                             expires=self.clock() + 900 if expired else doc["expires"])
                return
            except CosmosHttpResponseError as exc:
                if exc.status_code != 412:
                    raise
        raise HTTPException(429, "Espera unos minutos antes de volver a intentar.")

    def request(self, payload, config):
        try:
            user_id = AuthService.generate_user_id(payload.username.strip(), payload.campus)
            doc = self.users.read_item(user_id, user_id)
            if not doc.get("activo", True) or str(doc.get("email", "")).casefold() != str(payload.email).casefold():
                return
            previous = doc.get("password_recovery") or {}
            if self.clock() - previous.get("issued", 0) < 60:
                return
            secret = secrets.token_urlsafe(32)
            encoded_id = base64.urlsafe_b64encode(user_id.encode()).decode().rstrip("=")
            token = encoded_id + "." + secret
            digest = hashlib.sha256(token.encode()).hexdigest()
            self.replace(doc, password_recovery={"digest": digest, "issued": self.clock(),
                                                "expires": self.clock() + 900, "email": doc["email"],
                                                "password_fingerprint": hashlib.sha256(doc["password_hash"].encode()).hexdigest()})
            link = config["origin"] + "/recuperar#token=" + token
            self.sender(config, doc["email"], doc["username"], link, digest)
        except Exception as exc:
            # Igual respuesta pública para cuenta ausente y fallo de envío.
            logger.warning("password_recovery_request_failed type=%s", type(exc).__name__)

    def confirm(self, payload):
        valid, reason = AuthService.validate_password_strength(payload.password)
        if not valid or len(payload.password.encode("utf-8")) > 72:
            raise HTTPException(400, reason if not valid else "La contraseña supera el máximo de 72 bytes.")
        try:
            encoded_id, secret = payload.token.split(".")
            if len(secret) != 43:
                raise ValueError()
            user_id = base64.b64decode(encoded_id + "=" * (-len(encoded_id) % 4), altchars=b"-_", validate=True).decode()
            if not user_id.startswith("user:") or len(user_id) > 200:
                raise ValueError()
            doc = self.users.read_item(user_id, user_id)
            stored = doc.get("password_recovery") or {}
            matches = hmac.compare_digest(stored.get("digest", ""), hashlib.sha256(payload.token.encode()).hexdigest())
            fingerprint = hashlib.sha256(doc["password_hash"].encode()).hexdigest()
            if not matches or stored.get("expires", 0) <= self.clock() or not doc.get("activo", True) or stored.get("email") != doc.get("email") or stored.get("password_fingerprint") != fingerprint:
                raise ValueError()
            self.replace(doc, password_hash=AuthService.hash_password(payload.password), password_recovery=None,
                         intentos_fallidos=0, bloqueado_hasta=None)
        except (ValueError, KeyError, UnicodeError):
            raise HTTPException(400, INVALID)
        except CosmosHttpResponseError as exc:
            if exc.status_code in (404, 412):
                raise HTTPException(400, INVALID) from exc
            raise HTTPException(503, "El servicio no está disponible. Intenta de nuevo.") from exc
        try:
            self.audit.create_item({"id": "audit:password-reset:" + secrets.token_hex(16),
                                   "usuario": doc["username"], "accion": "UPDATE_USER", "recurso": user_id,
                                   "detalles": "Contraseña restablecida mediante enlace por correo",
                                   "timestamp": datetime.now(timezone.utc).isoformat()})
        except Exception as exc:
            logger.warning("password_recovery_audit_failed type=%s", type(exc).__name__)
        return {"message": "Contraseña actualizada. Ya puedes iniciar sesión con tu contraseña nueva."}


def build_recovery_router(users, audit):
    router = APIRouter(prefix="/auth/password-recovery", tags=["Recuperación de acceso"])
    service = RecoveryService(users, audit)

    @router.get("/status")
    def status():
        return {"enabled": mail_config() is not None}

    @router.post("/request", status_code=202)
    def request(payload: RecoveryRequest, request: Request, background: BackgroundTasks):
        config = mail_config()
        if not config:
            raise HTTPException(503, "La recuperación por correo aún no está habilitada. Contacta al responsable de SASU.")
        try:
            service.limit("request:" + (request.client.host if request.client else "unknown"), 10)
            service.limit("request:global", 100)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "El servicio no está disponible. Intenta de nuevo.")
        background.add_task(service.request, payload, config)
        return {"message": GENERIC}

    @router.post("/confirm")
    def confirm(payload: RecoveryConfirmation, request: Request):
        if not mail_config():
            raise HTTPException(503, "La recuperación por correo aún no está habilitada.")
        try:
            service.limit("confirm:" + (request.client.host if request.client else "unknown"), 20)
            return service.confirm(payload)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "El servicio no está disponible. Intenta de nuevo.")

    return router
