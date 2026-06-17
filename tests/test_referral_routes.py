import asyncio
import os
import sys
import types
import unittest
from pathlib import Path

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ.setdefault("COSMOS_URL", "https://localhost:8081")
os.environ.setdefault("COSMOS_KEY", "test-key")
os.environ.setdefault("COSMOS_DB", "test-db")

email_validator_stub = types.ModuleType("email_validator")
email_validator_stub.EmailNotValidError = ValueError
email_validator_stub.validate_email = lambda email, check_deliverability=False: {
    "normalized": email,
    "local_part": email.split("@", 1)[0],
    "domain": email.split("@", 1)[1] if "@" in email else "",
}
sys.modules.setdefault("email_validator", email_validator_stub)

import pydantic.networks as pydantic_networks

_metadata_version = pydantic_networks.version
pydantic_networks.version = lambda package: "2.0.0" if package == "email-validator" else _metadata_version(package)

from auth_models import Campus, TokenData, UserRole
from referral_models import CounterReferralCreate, ReferralCreate, ReferralUpdateStatus
from referral_repository import ReferralNotFoundError
import referral_routes


class FakeReferralRepository:
    def __init__(self):
        self.referrals = {}

    def create_referral(self, referral):
        self.referrals[referral["id"]] = dict(referral)
        return self.referrals[referral["id"]]

    def get_referral(self, referral_id):
        if referral_id not in self.referrals:
            raise ReferralNotFoundError(referral_id)
        return self.referrals[referral_id]

    def list_referrals(self, filters=None):
        filters = filters or {}
        values = list(self.referrals.values())
        if filters.get("status"):
            values = [item for item in values if item.get("status") == filters["status"]]
        if filters.get("priority"):
            values = [item for item in values if item.get("priority") == filters["priority"]]
        if filters.get("origin_area"):
            values = [item for item in values if item.get("origin", {}).get("area") == filters["origin_area"]]
        if filters.get("destination_area"):
            values = [item for item in values if item.get("destination", {}).get("area") == filters["destination_area"]]
        if filters.get("matricula"):
            values = [item for item in values if item.get("student", {}).get("matricula") == filters["matricula"]]
        if filters.get("student_name"):
            needle = filters["student_name"].lower()
            values = [item for item in values if needle in item.get("student", {}).get("nombre", "").lower()]
        return values

    def list_student_referrals(self, matricula):
        return [
            item for item in self.referrals.values()
            if item.get("student", {}).get("matricula") == matricula
        ]

    def list_pending_referrals(self, area=None):
        values = [
            item for item in self.referrals.values()
            if item.get("status") in {"sent", "received", "accepted"}
        ]
        if area:
            values = [item for item in values if item.get("destination", {}).get("area") == area]
        return values

    def update_referral(self, referral_id, updates):
        referral = self.get_referral(referral_id)
        referral.update(updates)
        self.referrals[referral_id] = referral
        return referral


def sample_payload(origin="medico", destination="psicologia", send=True):
    return ReferralCreate(
        student={
            "matricula": "15662",
            "nombre": "Alumno Prueba",
            "correo": "alumno@example.edu",
            "campus": "CRES Llano Largo",
        },
        originArea=origin,
        destinationArea=destination,
        priority="media",
        reason="Valoracion institucional",
        observations="Observacion opcional",
        send=send,
    )


class ReferralRouteTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeReferralRepository()
        self.medico = TokenData(
            username="medico1",
            rol=UserRole.MEDICO,
            campus=Campus.CRES_LLANO_LARGO,
        )
        self.psicologia = TokenData(
            username="psico1",
            rol=UserRole.PSICOLOGIA,
            campus=Campus.CRES_LLANO_LARGO,
        )

    def create_referral(self, payload=None, user=None):
        return asyncio.run(
            referral_routes.create_referral(
                payload or sample_payload(),
                current_user=user or self.medico,
                repository=self.repo,
            )
        )

    def test_create_referral_sent(self):
        referral = self.create_referral()
        self.assertEqual(referral["status"], "sent")
        self.assertEqual(referral["origin"]["area"], "medico")
        self.assertEqual(referral["destination"]["area"], "psicologia")
        self.assertEqual(len(referral["statusHistory"]), 1)

    def test_user_cannot_create_from_other_area(self):
        with self.assertRaises(HTTPException) as context:
            self.create_referral(sample_payload(origin="psicologia"), user=self.medico)
        self.assertEqual(context.exception.status_code, 403)

    def test_list_referrals_is_scoped_by_area(self):
        visible = self.create_referral()
        hidden = self.create_referral(
            sample_payload(origin="nutricion", destination="odontologia"),
            user=TokenData(
                username="admin",
                rol=UserRole.ADMIN,
                campus=Campus.CRES_LLANO_LARGO,
            ),
        )

        referrals = asyncio.run(
            referral_routes.list_referrals(
                status_filter=None,
                current_user=self.psicologia,
                repository=self.repo,
            )
        )

        ids = [item["id"] for item in referrals]
        self.assertIn(visible["id"], ids)
        self.assertNotIn(hidden["id"], ids)

    def test_invalid_transition_is_rejected(self):
        referral = self.create_referral()
        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                referral_routes.update_referral_status(
                    referral["id"],
                    ReferralUpdateStatus(status="scheduled"),
                    current_user=self.psicologia,
                    repository=self.repo,
                )
            )
        self.assertEqual(context.exception.status_code, 409)

    def test_destination_can_receive_reference(self):
        referral = self.create_referral()
        updated = asyncio.run(
            referral_routes.update_referral_status(
                referral["id"],
                ReferralUpdateStatus(status="received", note="Recibida"),
                current_user=self.psicologia,
                repository=self.repo,
            )
        )
        self.assertEqual(updated["status"], "received")
        self.assertIsNotNone(updated["receivedAt"])
        self.assertEqual(len(updated["statusHistory"]), 2)

    def test_counter_referral_rejected_when_closed(self):
        referral = self.create_referral()
        self.repo.update_referral(referral["id"], {"status": "closed"})
        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                referral_routes.add_counter_referral(
                    referral["id"],
                    CounterReferralCreate(summary="Respuesta institucional"),
                    current_user=self.psicologia,
                    repository=self.repo,
                )
            )
        self.assertEqual(context.exception.status_code, 409)

    def test_pending_referrals_uses_user_area(self):
        referral = self.create_referral()
        self.create_referral(
            sample_payload(origin="nutricion", destination="odontologia"),
            user=TokenData(
                username="admin",
                rol=UserRole.ADMIN,
                campus=Campus.CRES_LLANO_LARGO,
            ),
        )
        pending = asyncio.run(
            referral_routes.list_pending_referrals(
                current_user=self.psicologia,
                repository=self.repo,
            )
        )
        self.assertEqual([item["id"] for item in pending], [referral["id"]])


if __name__ == "__main__":
    unittest.main()
