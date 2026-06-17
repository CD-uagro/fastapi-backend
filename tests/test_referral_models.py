import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from referral_models import (
    ReferralCreate,
    ReferralPriority,
    ReferralStatus,
    VALID_REFERRAL_TRANSITIONS,
)


def sample_student():
    return {
        "matricula": "15662",
        "nombre": "Alumno Prueba",
        "correo": "alumno@example.edu",
        "campus": "CRES Llano Largo",
    }


class ReferralModelTests(unittest.TestCase):
    def test_referral_create_requires_reason(self):
        with self.assertRaises(ValueError):
            ReferralCreate(
                student=sample_student(),
                originArea="medico",
                destinationArea="psicologia",
                priority="media",
                reason=" ",
            )

    def test_referral_create_accepts_required_payload(self):
        payload = ReferralCreate(
            student=sample_student(),
            originArea="medico",
            destinationArea="psicologia",
            priority="alta",
            reason="Valoracion psicologica",
        )
        self.assertEqual(payload.priority, ReferralPriority.ALTA.value)
        self.assertEqual(payload.originArea, "medico")

    def test_valid_referral_transitions_include_mvp_flow(self):
        self.assertIn(ReferralStatus.SENT.value, VALID_REFERRAL_TRANSITIONS[ReferralStatus.DRAFT.value])
        self.assertIn(ReferralStatus.RECEIVED.value, VALID_REFERRAL_TRANSITIONS[ReferralStatus.SENT.value])
        self.assertIn(ReferralStatus.ACCEPTED.value, VALID_REFERRAL_TRANSITIONS[ReferralStatus.RECEIVED.value])
        self.assertIn(ReferralStatus.SCHEDULED.value, VALID_REFERRAL_TRANSITIONS[ReferralStatus.ACCEPTED.value])
        self.assertIn(ReferralStatus.CLOSED.value, VALID_REFERRAL_TRANSITIONS[ReferralStatus.ATTENDED.value])


if __name__ == "__main__":
    unittest.main()
