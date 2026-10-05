"""Pruebas de acceso con Cosmos sustituido: no conectan ni modifican datos reales."""
import importlib
import sys
import types
import unittest
import asyncio
import httpx
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from azure.cosmos.exceptions import CosmosHttpResponseError


class FakeCosmos:
    def __init__(self, *args):
        pass


cosmos = types.ModuleType("cosmos_helper")
cosmos.CosmosDBHelper = FakeCosmos
cosmos.get_cosmos_db_name = lambda: "test-db"
cosmos.get_citas_container = lambda: None
cosmos.get_citas_pk_path = lambda: "/id"
cosmos.upsert_cita = lambda *args: None
sys.modules["cosmos_helper"] = cosmos
with patch.dict(
    "os.environ", {"COSMOS_CONTAINER_CARNETS": "test", "COSMOS_CONTAINER_NOTAS": "test"}
):
    main = importlib.import_module("main")
from auth_models import UserInDB
from recover_access import replacement, ask_password
import argparse


class LocalClient:
    # ASGITransport permite probar sin servidor ni depender de TestClient antiguo.
    def request(self, method, url, **kwargs):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
                return await client.request(method, url, **kwargs)
        return asyncio.run(run())

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.client = LocalClient()
        self.document = dict(
            id="user:test@cres-llano-largo", username="test", email="test@example.com",
            password_hash="test-hash", nombre_completo="Test Admin", rol="admin",
            campus="cres-llano-largo", departamento="test", activo=True,
            fecha_creacion="2026-10-05T00:00:00", intentos_fallidos=0, bloqueado_hasta=None,
        )
        self.users = patch.object(main, "usuarios").start()
        self.audit = patch.object(main, "log_audit").start()
        self.verify = patch.object(main.AuthService, "verify_password", return_value=True).start()
        self.users.read_item.return_value = self.document.copy()
        self.addCleanup(patch.stopall)

    def login(self, **extra):
        return self.client.post("/auth/login", json={"username": "test", "password": "example", **extra})

    def test_login_and_validate_session_without_explicit_campus(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("password_hash", response.json()["user"])
        self.users.read_item.assert_called_with(self.document["id"], self.document["id"])
        me = self.client.get("/auth/me", headers={"Authorization": "Bearer " + response.json()["access_token"]})
        self.assertEqual(me.status_code, 200)

    def test_missing_user_is_401_but_database_failure_is_503(self):
        self.users.read_item.side_effect = CosmosHttpResponseError(status_code=404, message="missing")
        self.assertEqual(self.login().status_code, 401)
        self.users.read_item.side_effect = CosmosHttpResponseError(status_code=429, message="private details")
        response = self.login()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private details", response.text)
        self.users.read_item.side_effect = TimeoutError("private connection details")
        self.assertEqual(self.login().status_code, 503)

    def test_lock_on_fifth_failure(self):
        self.document["intentos_fallidos"] = 4
        self.users.read_item.return_value = self.document
        self.verify.return_value = False
        self.assertEqual(self.login().status_code, 403)
        saved = self.users.upsert_item.call_args.args[0]
        self.assertEqual(saved["intentos_fallidos"], 5)
        self.assertIsNotNone(saved["bloqueado_hasta"])

    def test_expired_lock_starts_a_new_attempt_window(self):
        self.document.update(intentos_fallidos=5, bloqueado_hasta=(datetime.utcnow() - timedelta(minutes=1)).isoformat())
        self.users.read_item.return_value = self.document
        self.verify.return_value = False
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.users.upsert_item.call_args.args[0]["intentos_fallidos"], 1)

    def test_inactive_and_locked_accounts_do_not_verify_password(self):
        self.document["activo"] = False
        self.users.read_item.return_value = self.document
        self.assertEqual(self.login().status_code, 403)
        self.verify.assert_not_called()
        self.document.update(activo=True, bloqueado_hasta=(datetime.utcnow() + timedelta(minutes=5)).isoformat())
        self.assertEqual(self.login().status_code, 403)
        self.verify.assert_not_called()

    def test_current_search_contract_is_preserved(self):
        with patch.object(main, "carnets") as carnets:
            carnets.query_items.return_value = []
            response = self.client.get("/carnet/search?nombre=Nobody")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), [])
            carnets.query_items.assert_called_once()
            carnets.get_by_id.assert_not_called()

    def test_recovery_preserves_identity_permissions_and_original(self):
        original = {**self.document, "_etag": "etag", "custom": "keep"}
        updated = replacement(original, "new-hash")
        self.assertEqual(updated["password_hash"], "new-hash")
        for key in ("id", "username", "campus", "rol", "activo", "custom"):
            self.assertEqual(updated[key], original[key])
        self.assertEqual(original["password_hash"], "test-hash")
        self.assertNotIn("_etag", updated)

    def test_generated_password_hash_is_accepted_by_backend(self):
        password = "LocalTest123!"
        password_hash = main.AuthService.hash_password(password)
        # La verificación real se prueba sin el mock de acceso.
        patch.stopall()
        self.assertTrue(main.AuthService.verify_password(password, password_hash))
        self.assertFalse(main.AuthService.verify_password("AnotherPassword123!", password_hash))

    def test_recovery_rejects_mismatched_passwords(self):
        with patch("getpass.getpass", side_effect=["LocalTest123!", "Different123!"]):
            with self.assertRaises(SystemExit):
                ask_password(argparse.ArgumentParser())

    def test_recovery_page_is_public_and_returns_to_desktop_app(self):
        response = self.client.get("/recuperar")
        self.assertEqual(response.status_code, 200)
        self.assertIn("vuelve a la app SASU", response.text)
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")


if __name__ == "__main__":
    unittest.main()
