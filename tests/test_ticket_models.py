import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ticket_models import (
    TicketAppointmentUpdate,
    TicketCreate,
    TicketVideoCallUpdate,
    normalize_utc_iso,
)


class TicketModelTests(unittest.TestCase):
    def test_normalize_utc_iso_preserves_zulu_utc(self):
        self.assertEqual(
            normalize_utc_iso("2026-06-16T01:16:00Z"),
            "2026-06-16T01:16:00.000000Z",
        )

    def test_ticket_create_validates_https_video_url(self):
        with self.assertRaises(ValueError):
            TicketCreate(
                matricula="15662",
                nombrePaciente="Paciente Prueba",
                campus="cres-llano-largo",
                categoria="psicologia",
                prioridad="media",
                titulo="Solicitud de apoyo",
                descripcionInicial="Descripcion inicial",
                videoCallUrl="http://example.com",
            )

    def test_appointment_requires_utc_timestamp(self):
        payload = TicketAppointmentUpdate(
            appointmentMode="virtual",
            appointmentAtUtc="2026-06-16T01:16:00Z",
        )
        self.assertEqual(payload.appointmentAtUtc, "2026-06-16T01:16:00.000000Z")

    def test_videocall_requires_https(self):
        with self.assertRaises(ValueError):
            TicketVideoCallUpdate(videoCallUrl="javascript:alert(1)")


if __name__ == "__main__":
    unittest.main()
