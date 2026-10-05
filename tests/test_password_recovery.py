import argparse
import asyncio
import base64
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from azure.cosmos.exceptions import CosmosHttpResponseError
from fastapi import FastAPI, HTTPException
import httpx
from password_recovery import (
    RecoveryService, RecoveryRequest, RecoveryConfirmation, build_recovery_router, mail_config, GENERIC, send_email,
)


class MemoryUsers:
    def __init__(self, doc):
        self.docs = {doc["id"]: copy.deepcopy(doc)}
        self.container = self
        self.collision = False

    def read_item(self, item_id, partition_key):
        if item_id not in self.docs:
            raise CosmosHttpResponseError(status_code=404)
        return copy.deepcopy(self.docs[item_id])

    def create_item(self, doc):
        if doc["id"] in self.docs:
            raise CosmosHttpResponseError(status_code=409)
        saved = {**copy.deepcopy(doc), "_etag": "1"}
        self.docs[doc["id"]] = saved
        return saved

    def replace_item(self, item_id, doc, etag, match_condition):
        current = self.docs[item_id]
        if self.collision or etag != current["_etag"]:
            raise CosmosHttpResponseError(status_code=412)
        saved = {**copy.deepcopy(doc), "_etag": str(int(etag) + 1)}
        self.docs[item_id] = saved
        return saved


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.now = 2000000
        self.user = {
            "id": "user:tester@cres-llano-largo", "username": "tester", "campus": "cres-llano-largo",
            "email": "tester@example.com", "rol": "medico", "activo": True, "password_hash": "old-hash",
            "intentos_fallidos": 5, "bloqueado_hasta": "later", "_etag": "1", "custom": "preserve",
        }
        self.users = MemoryUsers(self.user)
        self.audit, self.sender = Mock(), Mock()
        self.service = RecoveryService(self.users, self.audit, self.sender, lambda: self.now)
        self.config = {"origin": "https://sasu.test", "sender": "SASU <access@example.com>", "key": "test-key"}
        self.payload = RecoveryRequest(username="tester", campus="cres-llano-largo", email="tester@example.com")

    def issue(self):
        self.service.request(self.payload, self.config)
        return self.sender.call_args.args[3].split("#token=")[1]

    def confirm(self, token):
        with patch("password_recovery.AuthService.hash_password", return_value="new-hash"):
            return self.service.confirm(RecoveryConfirmation(token=token, password="NewPassword123!"))

    def test_issue_has_no_plain_token_in_database_and_does_not_change_password(self):
        token = self.issue()
        doc = self.users.docs[self.user["id"]]
        self.assertNotIn(token, str(doc))
        self.assertEqual(doc["password_hash"], "old-hash")
        self.assertEqual(doc["password_recovery"]["expires"], self.now + 900)
        self.assertEqual(self.sender.call_args.args[1], self.user["email"])

    def test_confirm_is_single_use_and_preserves_existing_account(self):
        token = self.issue()
        self.confirm(token)
        doc = self.users.docs[self.user["id"]]
        for key in ("id", "username", "rol", "campus", "email", "activo", "custom"):
            self.assertEqual(doc[key], self.user[key])
        self.assertEqual(doc["password_hash"], "new-hash")
        self.assertEqual(doc["intentos_fallidos"], 0)
        self.assertIsNone(doc["bloqueado_hasta"])
        self.assertIsNone(doc["password_recovery"])
        with self.assertRaises(HTTPException) as error:
            self.confirm(token)
        self.assertEqual(error.exception.status_code, 400)

    def test_expired_tampered_and_newer_link(self):
        token = self.issue()
        with self.assertRaises(HTTPException):
            self.confirm(token[:-1] + ("a" if token[-1] != "a" else "b"))
        self.now += 61
        new_token = self.issue()
        with self.assertRaises(HTTPException):
            self.confirm(token)
        self.now += 900
        with self.assertRaises(HTTPException):
            self.confirm(new_token)
        self.assertEqual(self.users.docs[self.user["id"]]["password_hash"], "old-hash")

    def test_account_email_password_or_active_state_change_invalidates_link(self):
        for changes in ({"email": "new@example.com"}, {"activo": False}, {"password_hash": "changed"}):
            self.setUp()
            token = self.issue()
            self.users.docs[self.user["id"]].update(changes)
            with self.assertRaises(HTTPException):
                self.confirm(token)

    def test_wrong_details_and_disabled_account_do_not_send_mail(self):
        wrong = RecoveryRequest(username="unknown", campus="cres-llano-largo", email="tester@example.com")
        self.service.request(wrong, self.config)
        wrong = RecoveryRequest(username="tester", campus="cres-llano-largo", email="wrong@example.com")
        self.service.request(wrong, self.config)
        self.users.docs[self.user["id"]]["activo"] = False
        self.service.request(self.payload, self.config)
        self.sender.assert_not_called()

    def test_concurrent_consumption_does_not_overwrite_account(self):
        token = self.issue()
        self.users.collision = True
        with self.assertRaises(HTTPException) as error:
            self.confirm(token)
        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(self.users.docs[self.user["id"]]["password_hash"], "old-hash")

    def test_weak_or_oversize_utf8_password_does_not_consume_token(self):
        token = self.issue()
        for password in ("weakweak", "A1" + "é" * 40):
            with self.assertRaises(HTTPException):
                self.service.confirm(RecoveryConfirmation(token=token, password=password))
        self.assertIsNotNone(self.users.docs[self.user["id"]]["password_recovery"])

    def test_cooldown_and_persistent_rate_limits(self):
        self.issue()
        self.service.request(self.payload, self.config)
        self.sender.assert_called_once()
        self.service.limit("test-ip", 2)
        # Otra instancia comparte el contador de Cosmos.
        other = RecoveryService(self.users, self.audit, self.sender, lambda: self.now)
        other.limit("test-ip", 2)
        with self.assertRaises(HTTPException) as error:
            other.limit("test-ip", 2)
        self.assertEqual(error.exception.status_code, 429)
        self.now += 901
        other.limit("test-ip", 2)

    def test_configuration_is_opt_in_and_rejects_injected_origins(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(mail_config())
        with patch.dict("os.environ", {"PASSWORD_RESET_ENABLED": "true", "RESEND_API_KEY": "key", "PASSWORD_RESET_FROM": "access@example.com"}):
            self.assertIsNotNone(mail_config())
            with patch.dict("os.environ", {"PASSWORD_RESET_BASE_URL": "https://attacker@other.test"}):
                self.assertIsNone(mail_config())

    def test_email_adapter_uses_registered_recipient_and_bounded_https_request(self):
        with patch("password_recovery.urllib.request.urlopen") as send:
            send.return_value.__enter__.return_value.status = 200
            send_email(self.config, self.user["email"], self.user["username"], "https://sasu.test/admin/recover.html#token=secret", "digest")
            req = send.call_args.args[0]
            self.assertEqual(req.full_url, "https://api.resend.com/emails")
            self.assertEqual(send.call_args.kwargs["timeout"], 10)
            self.assertEqual(json.loads(req.data)["to"], [self.user["email"]])
            self.assertNotIn("old-hash", req.data.decode())

    def test_sender_failure_preserves_password_and_does_not_expose_link(self):
        self.sender.side_effect = RuntimeError("provider_error")
        self.service.request(self.payload, self.config)
        self.assertEqual(self.users.docs[self.user["id"]]["password_hash"], "old-hash")

    def test_routes_generic_response_for_existing_and_missing_accounts(self):
        async def run():
            app = FastAPI()
            app.include_router(build_recovery_router(self.users, self.audit))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
                with patch("password_recovery.mail_config", return_value=self.config), patch("password_recovery.send_email"):
                    # Constructor's default sender captures the real function; patch the class request to avoid sends.
                    with patch.object(RecoveryService, "request"):
                        for username in ("tester", "unknown"):
                            result = await client.post("/auth/password-recovery/request", json={
                                "username": username, "campus": "cres-llano-largo", "email": "tester@example.com"})
                            self.assertEqual(result.status_code, 202)
                            self.assertEqual(result.json(), {"message": GENERIC})
                with patch("password_recovery.mail_config", return_value=None):
                    result = await client.post("/auth/password-recovery/request", json=self.payload.dict())
                    self.assertEqual(result.status_code, 503)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
