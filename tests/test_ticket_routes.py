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

    def list_tickets(self, filters=None):
        filters = filters or {}
        values = list(self.tickets.values())
        if filters.get("status"):
            values = [ticket for ticket in values if ticket.get("estado") == filters["status"]]
        if filters.get("category"):
            values = [ticket for ticket in values if ticket.get("categoria") == filters["category"]]
        if filters.get("priority"):
            values = [ticket for ticket in values if ticket.get("prioridad") == filters["priority"]]
        if filters.get("campus"):
            values = [ticket for ticket in values if ticket.get("campus") == filters["campus"]]
        if filters.get("unidad_academica"):
            values = [
                ticket
                for ticket in values
                if ticket.get("unidad_academica") == filters["unidad_academica"]
                or ticket.get("unidadAcademica") == filters["unidad_academica"]
            ]
        if filters.get("preparatoria"):
            values = [ticket for ticket in values if ticket.get("preparatoria") == filters["preparatoria"]]
        if filters.get("student_id"):
            values = [
                ticket
                for ticket in values
                if ticket.get("student_id") == filters["student_id"]
                or ticket.get("patientId") == filters["student_id"]
                or ticket.get("matricula") == filters["student_id"]
            ]
        if filters.get("matricula"):
            values = [ticket for ticket in values if ticket.get("matricula") == filters["matricula"]]
        return values

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

    def add_followup(self, ticket_id, followup):
        self.get_ticket(ticket_id)
        created = dict(followup)
        self.messages.setdefault(ticket_id, []).append(created)
        self.update_ticket(ticket_id, {"lastFollowupAtUtc": created.get("createdAtUtc")})
        return created

    def list_followups(self, ticket_id):
        self.get_ticket(ticket_id)
        return [
            message
            for message in self.messages.get(ticket_id, [])
            if message.get("metadata", {}).get("messageType") == "followup" or message.get("visibility")
        ]


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

    def test_internal_user_can_access_other_campus_ticket(self):
        ticket = self.create_ticket()
        self.repo.tickets[ticket["id"]]["campus"] = "clinica-acapulco"

        body = asyncio.run(
            ticket_routes.get_ticket_detail(
                ticket["id"],
                current_user=self.user,
                repository=self.repo,
            )
        )

        self.assertEqual(body["ticket"]["id"], ticket["id"])

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

    def test_admin_list_tickets_filters_without_campus_restriction(self):
        own_ticket = self.create_ticket()
        self.repo.tickets[own_ticket["id"]]["campus"] = "clinica-acapulco"
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
            ticket_routes.list_tickets(
                status_filter="abierto",
                category=None,
                priority=None,
                campus="clinica-acapulco",
                unidad_academica=None,
                preparatoria=None,
                student_id=None,
                matricula=None,
                current_user=self.user,
                repository=self.repo,
            )
        )

        self.assertEqual([ticket["id"] for ticket in tickets], [own_ticket["id"]])
        self.assertNotIn(other_ticket["id"], [ticket["id"] for ticket in tickets])

    def test_student_cannot_use_admin_list_tickets(self):
        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                ticket_routes.list_tickets(
                    status_filter=None,
                    category=None,
                    priority=None,
                    campus=None,
                    unidad_academica=None,
                    preparatoria=None,
                    student_id=None,
                    matricula=None,
                    current_user=self.student_user("15662"),
                    repository=self.repo,
                )
            )

        self.assertEqual(context.exception.status_code, 403)

    def test_admin_status_update_records_history(self):
        ticket = self.create_ticket()

        response = asyncio.run(
            ticket_routes.update_ticket_status(
                ticket["id"],
                TicketStatusUpdate(estado="en_revision"),
                current_user=self.user,
                repository=self.repo,
            )
        )

        self.assertEqual(response["estado"], "en_revision")
        self.assertEqual(response["statusHistory"][0]["previousStatus"], "abierto")
        self.assertEqual(response["statusHistory"][0]["newStatus"], "en_revision")
        self.assertEqual(response["statusHistory"][0]["changedBy"], self.user.username)

    def test_invalid_admin_status_is_rejected(self):
        with self.assertRaises(ValueError):
            TicketStatusUpdate(estado="estado_invalido")

    def test_admin_followup_is_added_to_ticket_history(self):
        ticket = self.create_ticket()

        followup = asyncio.run(
            ticket_routes.add_ticket_followup(
                ticket["id"],
                ticket_routes.TicketFollowupCreate(
                    message="Se canaliza para revision interna",
                    visibility="internal",
                ),
                current_user=self.user,
                repository=self.repo,
            )
        )

        self.assertEqual(followup["ticket_id"], ticket["id"])
        self.assertEqual(followup["author"], self.user.username)
        self.assertEqual(followup["role"], self.user.rol.value)
        self.assertEqual(followup["visibility"], "internal")

        detail = asyncio.run(
            ticket_routes.get_ticket_detail(
                ticket["id"],
                current_user=self.user,
                repository=self.repo,
            )
        )
        self.assertEqual(len(detail["followups"]), 1)

    def test_student_messages_exclude_internal_followups(self):
        ticket = self.create_ticket()
        student = self.student_user("15662")

        student_message = asyncio.run(
            ticket_routes.add_ticket_message(
                ticket["id"],
                TicketMessageCreate(message="Mensaje del alumno"),
                current_user=student,
                repository=self.repo,
            )
        )
        internal_followup = asyncio.run(
            ticket_routes.add_ticket_followup(
                ticket["id"],
                ticket_routes.TicketFollowupCreate(
                    message="Nota solo para operadores",
                    visibility="internal",
                ),
                current_user=self.user,
                repository=self.repo,
            )
        )
        student_followup = asyncio.run(
            ticket_routes.add_ticket_followup(
                ticket["id"],
                ticket_routes.TicketFollowupCreate(
                    message="Respuesta visible para alumno",
                    visibility="student",
                ),
                current_user=self.user,
                repository=self.repo,
            )
        )

        self.assertEqual(student_message["senderRole"], "alumno")
        self.assertEqual(internal_followup["visibility"], "internal")
        self.assertEqual(student_followup["visibility"], "student")

        messages = asyncio.run(
            ticket_routes.get_ticket_messages(
                ticket["id"],
                current_user=student,
                repository=self.repo,
            )
        )

        self.assertEqual(
            [message["message"] for message in messages],
            ["Mensaje del alumno", "Respuesta visible para alumno"],
        )

    def test_internal_user_messages_include_all_followups(self):
        ticket = self.create_ticket()

        asyncio.run(
            ticket_routes.add_ticket_followup(
                ticket["id"],
                ticket_routes.TicketFollowupCreate(
                    message="Nota interna",
                    visibility="internal",
                ),
                current_user=self.user,
                repository=self.repo,
            )
        )
        asyncio.run(
            ticket_routes.add_ticket_followup(
                ticket["id"],
                ticket_routes.TicketFollowupCreate(
                    message="Respuesta para alumno",
                    visibility="student",
                ),
                current_user=self.user,
                repository=self.repo,
            )
        )

        messages = asyncio.run(
            ticket_routes.get_ticket_messages(
                ticket["id"],
                current_user=self.user,
                repository=self.repo,
            )
        )

        self.assertEqual(
            [message["message"] for message in messages],
            ["Nota interna", "Respuesta para alumno"],
        )

    def test_student_cannot_read_messages_for_other_student_ticket(self):
        payload = sample_ticket_payload()
        payload["matricula"] = "99999"
        ticket = asyncio.run(
            ticket_routes.create_ticket(
                TicketCreate(**payload),
                current_user=self.user,
                repository=self.repo,
            )
        )

        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                ticket_routes.get_ticket_messages(
                    ticket["id"],
                    current_user=self.student_user("15662"),
                    repository=self.repo,
                )
            )

        self.assertEqual(context.exception.status_code, 403)

    def test_empty_followup_is_rejected(self):
        with self.assertRaises(ValueError):
            ticket_routes.TicketFollowupCreate(message="", visibility="internal")

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
