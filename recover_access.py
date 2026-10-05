"""Recuperación administrativa por Cosmos. Sin --user-id solo consulta cuentas.

No elimina usuarios ni cambia institución, rol o identificador. La contraseña
se pide de forma oculta; no se recibe por argumentos ni se imprime.
"""
import argparse
import getpass
import os
from pathlib import Path
from datetime import datetime, timezone
import uuid
import warnings

from azure.cosmos import CosmosClient
from azure.core import MatchConditions
from dotenv import dotenv_values
from auth_service import AuthService


def replacement(document, password_hash):
    updated = {k: v for k, v in document.items() if not k.startswith("_")}
    updated.update(password_hash=password_hash, intentos_fallidos=0, bloqueado_hasta=None)
    return updated


def ask_password(parser):
    with warnings.catch_warnings():
        # No permitir la alternativa que muestra la contraseña sin terminal.
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass("Nueva contraseña (no se muestra al escribir): ")
        confirmation = getpass.getpass("Repite la nueva contraseña: ")
    valid, reason = AuthService.validate_password_strength(password)
    if not valid or len(password.encode("utf-8")) > 72:
        parser.exit(1, (reason if not valid else "Máximo 72 bytes de contraseña") + "\n")
    if password != confirmation:
        parser.exit(1, "Las contraseñas no coinciden.\n")
    return password


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", help="ID exacto de la cuenta que se recuperará")
    parser.add_argument("--hash-only", action="store_true", help="Generar un hash para actualizarlo manualmente en Azure; no conecta con Cosmos")
    args = parser.parse_args()
    if args.hash_only:
        if args.user_id:
            parser.error("Usa --hash-only sin --user-id")
        password_hash = AuthService.hash_password(ask_password(parser))
        print("\nCopia solo la siguiente línea en el campo password_hash de tu cuenta en Azure:")
        print(password_hash)
        print("La cuenta todavía no se ha modificado. Guarda el documento en Azure para aplicar el cambio.")
        return
    cfg = {**dotenv_values(Path(__file__).with_name(".env")), **os.environ}
    db_name = cfg.get("COSMOS_DB") or cfg.get("COSMOS_DATABASE")
    if not all((cfg.get("COSMOS_URL"), cfg.get("COSMOS_KEY"), db_name)):
        parser.exit(1, "Faltan COSMOS_URL, COSMOS_KEY o COSMOS_DB.\n")
    client = CosmosClient(cfg["COSMOS_URL"], credential=cfg["COSMOS_KEY"],
                         connection_timeout=10, read_timeout=10, retry_total=0)
    try:
        database = client.get_database_client(db_name)
        users = database.get_container_client(cfg.get("COSMOS_CONTAINER_USUARIOS", "usuarios"))
        if not args.user_id:
            for user in users.query_items(
                "SELECT c.id, c.username, c.campus, c.activo FROM c WHERE c.rol = 'admin'",
                enable_cross_partition_query=True,
            ):
                print(user)
            return
        user = users.read_item(args.user_id, args.user_id)
        if user.get("rol") != "admin" or not user.get("activo", True):
            parser.exit(1, "Se requiere una cuenta administrativa activa; revisar antes de continuar.\n")
        print(f"Base: {db_name}; cuenta: {user['username']}; institución: {user['campus']}")
        if input("Escribe el ID exacto para confirmar la recuperación: ") != args.user_id:
            parser.exit(1, "Cancelado. No se modificó la cuenta.\n")
        password = ask_password(parser)
        audit = database.get_container_client(cfg.get("COSMOS_CONTAINER_AUDITORIA", "auditoria"))
        event = {
            "id": f"audit:recovery:{uuid.uuid4().hex}",
            "usuario": user["username"], "accion": "UPDATE_USER", "recurso": user["id"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "detalles": "Recuperación administrativa solicitada desde consola; sin cambios de rol o institución",
        }
        # Si no puede registrar la intervención, no toca la cuenta.
        audit.create_item(event)
        users.replace_item(user["id"], replacement(user, AuthService.hash_password(password)),
                           etag=user["_etag"], match_condition=MatchConditions.IfNotModified)
        event["detalles"] = "Recuperación administrativa completada; contraseña y bloqueo restablecidos"
        try:
            audit.replace_item(event["id"], event)
        except Exception:
            print("Contraseña actualizada; quedó registrado el inicio, pero falta cerrar el evento de auditoría.")
        print("Cuenta conservada y contraseña actualizada. Usa la misma institución al iniciar sesión.")
        print("Las sesiones existentes no se revocan automáticamente en esta versión.")
    finally:
        client.close()


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit("Operación interrumpida.")
    except Exception as exc:
        # Nunca imprimir configuración, claves ni documentos completos.
        raise SystemExit(f"No se completó la recuperación ({type(exc).__name__}). Revisa configuración y conectividad.")
