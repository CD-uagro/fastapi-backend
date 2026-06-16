import os
import sys
import unittest
import asyncio
import types
from pathlib import Path

from fastapi import HTTPException
from jose import jwt

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
from auth_service import AuthService
from ticket_models import (
    TicketAppointmentUpdate,
    TicketAssignUpdate,
    TicketCreate,
    TicketMessageCreate,
    TicketStatusUpdate,
    TicketVideoCallUpdate,
)
from ticket_repository import TicketNotFoundError
import ticket_routes


class FakeTicketRepository:
    def __init__(self):
        self.tickets = {}
        self.messages = {}

    def create_ticket(self, ticket):
        self.tickets[ticket["id"]] = dict(ticket)
        return self.tickets[ticket["id"]]

    def get_ticket(self, ticket_id):
        if ticket_id not in self.tickets:
            raise TicketNotFoundError(ticket_id)
        return self.tickets[ticket_id]

    def list_my_tickets(self, username, campus, include_campus_queue=False):
        values = [ticket for ticket in self.tickets.values() if ticket["campus"] == campus]
        if include_campus_queue:
            return values
        return [
            ticket
            for ticket in values
            if ticket.get("createdBy") == username or ticket.get("assignedTo") == username
        ]

    def list_student_tickets(self, matricula, campus):
        return [
            ticket
            for ticket in self.tickets.values()
            if ticket["campus"] == campus and ticket.get("matricula") == matricula
        ]

    def update_ticket(self, ticket_id, updates):
        ticket = self.get_ticket(ticket_id)
        ticket.update(updates)
        self.tickets[ticket_id] = ticket
        return ticket

    def add_message(self, ticket_id, message):
        self.get_ticket(ticket_id)
        created = dict(message)
        self.messages.setdefault(ticket_id, []).append(created)
        self.update_ticket(
            ticket_id,
            {
                "lastMessageAtUtc": created["createdAtUtc"],
                "lastMessagePreview": created["message"][:120],
            },
        )
        return created

    def list_messages(self, ticket_id):
        self.get_ticket(ticket_id)
        return self.messages.get(ticket_id, [])


def sample_ticket_payload(campus="cres-llano-largo"):
    return {
        "matricula": "15662",
        "nombrePaciente": "Paciente Prueba",
        "campus": campus,
        "categoria": "psicologia",
        "prioridad": "media",
        "titulo": "Solicitud de apoyo",
        "descripcionInicial": "Necesito orientacion institucional",
    }


class TicketRouteTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeTicketRepository()
        self.user = TokenData(
            username="psico1",
            rol=UserRole.PSICOLOGIA,
            campus=Campus.CRES_LLANO_LARGO,
        )

    def create_ticket(self):
        return asyncio.run(
            ticket_routes.create_ticket(
                TicketCreate(**sample_ticket_payload()),
                current_user=self.user,
                repository=self.repo,
            )
        )

    def student_user(self, matricula="15662"):
        return ticket_routes.TicketPrincipal(
            username=f"student:{matricula}",
            rol="alumno",
            campus=Campus.CRES_LLANO_LARGO.value,
            matricula=matricula,
            nombre="Alumno Prueba",
            email="alumno@example.edu",
            is_student=True,
        )

    def test_create_and_get_ticket(self):
        ticket = self.create_ticket()
        body = asyncio.run(
            ticket_routes.get_ticket_detail(
                ticket["id"],
                current_user=self.user,
                repository=self.repo,
            )
        )
        self.assertEqual(body["ticket"]["id"], ticket["id"])
        self.assertEqual(body["ticket"]["estado"], "abierto")

    def test_add_and_get_messages(self):
        ticket = self.create_ticket()
        response = asyncio.run(
            ticket_routes.add_ticket_message(
                ticket["id"],
                TicketMessageCreate(message="Respuesta institucional"),
                current_user=self.user,
                repository=self.repo,
            )
        )
        self.assertEqual(response["message"], "Respuesta institucional")

        messages = asyncio.run(
            ticket_routes.get_ticket_messages(
                ticket["id"],
                current_user=self.user,
                repository=self.repo,
            )
        )
        self.assertEqual(len(messages), 1)

    def test_assign_status_appointment_videocall_and_close(self):
        ticket = self.create_ticket()

        response = asyncio.run(
            ticket_routes.assign_ticket(
                ticket["id"],
                TicketAssignUpdate(assignedTo="medico1", assignedArea="medicina"),
                current_user=self.user,
                repository=self.repo,
            )
        )
        self.assertEqual(response["estado"], "asignado")

        response = asyncio.run(
            ticket_routes.update_ticket_status(
                ticket["id"],
                TicketStatusUpdate(estado="en_atencion"),
                current_user=self.user,
                repository=self.repo,
            )
        )
        self.assertEqual(response["estado"], "en_atencion")

        response = asyncio.run(
            ticket_routes.update_ticket_appointment(
                ticket["id"],
                TicketAppointmentUpdate(
                    appointmentMode="virtual",
                    appointmentAtUtc="2026-06-16T01:16:00Z",
                ),
                current_user=self.user,
                repository=self.repo,
            )
        )
        self.assertEqual(response["appointmentMode"], "virtual")
        self.assertEqual(response["appointmentAtUtc"], "2026-06-16T01:16:00.000000Z")

        response = asyncio.run(
            ticket_routes.update_ticket_videocall(
                ticket["id"],
                TicketVideoCallUpdate(videoCallUrl="https://meet.google.com/abc-defg-hij"),
                current_user=self.user,
                repository=self.repo,
            )
        )
        self.assertEqual(response["videoCallUrl"], "https://meet.google.com/abc-defg-hij")

        response = asyncio.run(
            ticket_routes.update_ticket_status(
                ticket["id"],
                TicketStatusUpdate(estado="cerrado"),
                current_user=self.user,
                repository=self.repo,
            )
        )
        self.assertEqual(response["estado"], "cerrado")
        self.assertIsNotNone(response["closedAtUtc"])

    def test_cannot_access_other_campus_ticket(self):
        ticket = self.create_ticket()
        self.repo.tickets[ticket["id"]]["campus"] = "clinica-acapulco"

        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                ticket_routes.get_ticket_detail(
                    ticket["id"],
                    current_user=self.user,
                    repository=self.repo,
                )
            )
        self.assertEqual(context.exception.status_code, 403)

    def test_read_only_user_cannot_reply(self):
        ticket = self.create_ticket()
        read_only = TokenData(
            username="lector1",
            rol=UserRole.LECTURA,
            campus=Campus.CRES_LLANO_LARGO,
        )
        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                ticket_routes.add_ticket_message(
                    ticket["id"],
                    TicketMessageCreate(message="No debo poder responder"),
                    current_user=read_only,
                    repository=self.repo,
                )
        )
        self.assertEqual(context.exception.status_code, 403)

    def test_internal_user_my_tickets_still_filters_username(self):
        own_ticket = self.create_ticket()
        assigned_payload = sample_ticket_payload()
        assigned_payload["matricula"] = "99123"
        assigned_ticket = asyncio.run(
            ticket_routes.create_ticket(
                TicketCreate(**assigned_payload),
                current_user=self.user,
                repository=self.repo,
            )
        )
        self.repo.tickets[assigned_ticket["id"]]["createdBy"] = "medico1"
        self.repo.tickets[assigned_ticket["id"]]["assignedTo"] = self.user.username

        other_payload = sample_ticket_payload()
        other_payload["matricula"] = "88456"
        other_ticket = asyncio.run(
            ticket_routes.create_ticket(
                TicketCreate(**other_payload),
                current_user=self.user,
                repository=self.repo,
            )
        )
        self.repo.tickets[other_ticket["id"]]["createdBy"] = "medico1"
        self.repo.tickets[other_ticket["id"]]["assignedTo"] = "medico2"

        tickets = asyncio.run(
            ticket_routes.get_my_tickets(
                current_user=self.user,
                repository=self.repo,
            )
        )
        self.assertEqual({ticket["id"] for ticket in tickets}, {own_ticket["id"], assigned_ticket["id"]})

    def test_student_token_with_role_claim_is_accepted(self):
        token = AuthService.create_access_token(
            {
                "sub": "carnet-digital",
                "role": "alumno",
                "matricula": "15662",
                "nombre": "Alumno Prueba",
                "email": "alumno@example.edu",
                "campus": Campus.CRES_LLANO_LARGO.value,
            }
        )

        principal = asyncio.run(ticket_routes.get_ticket_principal(token=token))

        self.assertTrue(principal.is_student)
        self.assertEqual(principal.username, "student:15662")
        self.assertEqual(principal.rol, "alumno")
        self.assertEqual(principal.matricula, "15662")
        self.assertEqual(principal.nombre, "Alumno Prueba")
        self.assertEqual(principal.email, "alumno@example.edu")

    def test_student_secret_token_with_role_claim_is_accepted(self):
        os.environ["STUDENT_JWT_SECRET"] = "student-test-secret"
        token = jwt.encode(
            {
                "sub": "carnet-digital",
                "role": "alumno",
                "matricula": "15662",
                "nombre": "Alumno Prueba",
                "email": "alumno@example.edu",
                "campus": Campus.CRES_LLANO_LARGO.value,
            },
            "student-test-secret",
            algorithm="HS256",
        )

        principal = asyncio.run(ticket_routes.get_ticket_principal(token=token))

        self.assertTrue(principal.is_student)
        self.assertEqual(principal.username, "student:15662")
        self.assertEqual(principal.rol, "alumno")
        self.assertEqual(principal.matricula, "15662")
        self.assertEqual(principal.nombre, "Alumno Prueba")
        self.assertEqual(principal.email, "alumno@example.edu")

    def test_student_secret_token_with_matricula_only_is_accepted(self):
        os.environ["STUDENT_JWT_SECRET"] = "student-test-secret"
        token = jwt.encode(
            {
                "matricula": "15662",
                "nombre": "Alumno Prueba",
                "email": "alumno@example.edu",
            },
            "student-test-secret",
            algorithm="HS256",
        )

        principal = asyncio.run(ticket_routes.get_ticket_principal(token=token))

        self.assertTrue(principal.is_student)
        self.assertEqual(principal.username, "student:15662")
        self.assertEqual(principal.rol, "alumno")
        self.assertEqual(principal.campus, Campus.CRES_LLANO_LARGO.value)
        self.assertEqual(principal.matricula, "15662")

    def test_student_only_sees_tickets_for_own_matricula(self):
        own_ticket = self.create_ticket()
        other_payload = sample_ticket_payload()
        other_payload["matricula"] = "99999"
        other_ticket = asyncio.run(
            ticket_routes.create_ticket(
                TicketCreate(**other_payload),
                current_user=self.user,
                repository=self.repo,
            )
        )

        tickets = asyncio.run(
            ticket_routes.get_my_tickets(
                current_user=self.student_user("15662"),
                repository=self.repo,
            )
        )

        self.assertEqual([ticket["id"] for ticket in tickets], [own_ticket["id"]])
        self.assertNotIn(other_ticket["id"], [ticket["id"] for ticket in tickets])

    def test_student_create_ticket_uses_token_identity(self):
        payload = sample_ticket_payload(campus=Campus.CLINICA_ACAPULCO.value)
        payload["nombrePaciente"] = "Nombre Manipulado"

        ticket = asyncio.run(
            ticket_routes.create_ticket(
                TicketCreate(**payload),
                current_user=self.student_user("15662"),
                repository=self.repo,
            )
        )

        self.assertEqual(ticket["createdBy"], "student:15662")
        self.assertEqual(ticket["createdByRole"], "alumno")
        self.assertEqual(ticket["matricula"], "15662")
        self.assertEqual(ticket["patientId"], "15662")
        self.assertEqual(ticket["nombrePaciente"], "Alumno Prueba")
        self.assertEqual(ticket["email"], "alumno@example.edu")
        self.assertEqual(ticket["campus"], Campus.CRES_LLANO_LARGO.value)

    def test_student_cannot_create_ticket_for_other_matricula(self):
        payload = sample_ticket_payload()
        payload["matricula"] = "99999"

        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                ticket_routes.create_ticket(
                    TicketCreate(**payload),
                    current_user=self.student_user("15662"),
                    repository=self.repo,
                )
            )

        self.assertEqual(context.exception.status_code, 403)

    def test_missing_token_returns_401(self):
        with self.assertRaises(HTTPException) as context:
            asyncio.run(ticket_routes.get_ticket_principal(token=""))

        self.assertEqual(context.exception.status_code, 401)

    def test_unauthorized_role_returns_403(self):
        unauthorized = ticket_routes.TicketPrincipal(
            username="visitante1",
            rol="visitante",
            campus=Campus.CRES_LLANO_LARGO.value,
        )

        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                ticket_routes.get_my_tickets(
                    current_user=unauthorized,
                    repository=self.repo,
                )
            )

        self.assertEqual(context.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
