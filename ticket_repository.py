import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from azure.cosmos.exceptions import CosmosHttpResponseError

from cosmos_helper import CosmosDBHelper
from ticket_models import TicketEstado, utc_now_iso


class TicketNotFoundError(Exception):
    pass


class TicketRepositoryError(Exception):
    pass


def generate_ticket_id() -> str:
    return f"ticket:{uuid.uuid4()}"


def generate_ticket_message_id() -> str:
    return f"ticketmsg:{uuid.uuid4()}"


def generate_ticket_number(now: Optional[datetime] = None) -> str:
    current = now or datetime.now(timezone.utc)
    return f"SASU-{current.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


class CosmosTicketRepository:
    def __init__(
        self,
        tickets_helper: Optional[CosmosDBHelper] = None,
        messages_helper: Optional[CosmosDBHelper] = None,
    ):
        self.tickets = tickets_helper or CosmosDBHelper(
            os.environ.get("COSMOS_CONTAINER_TICKETS", "tickets"), "/campus"
        )
        self.messages = messages_helper or CosmosDBHelper(
            os.environ.get("COSMOS_CONTAINER_TICKET_MESSAGES", "ticket_messages"), "/ticketId"
        )

    def create_ticket(self, ticket: Dict[str, Any]) -> Dict[str, Any]:
        ticket.setdefault("id", generate_ticket_id())
        ticket.setdefault("ticketNumber", generate_ticket_number())
        ticket.setdefault("deleted", False)
        ticket.setdefault("schemaVersion", 1)
        try:
            return self.tickets.create_item(ticket)
        except CosmosHttpResponseError as exc:
            raise TicketRepositoryError(str(exc))

    def get_ticket(self, ticket_id: str) -> Dict[str, Any]:
        query = "SELECT * FROM c WHERE c.id = @id AND (NOT IS_DEFINED(c.deleted) OR c.deleted = false)"
        params = [{"name": "@id", "value": ticket_id}]
        results = self.tickets.query_items(query, params)
        if not results:
            raise TicketNotFoundError(ticket_id)
        return results[0]

    def list_my_tickets(self, username: str, campus: str, include_campus_queue: bool = False) -> List[Dict[str, Any]]:
        if include_campus_queue:
            query = (
                "SELECT * FROM c WHERE c.campus = @campus "
                "AND (NOT IS_DEFINED(c.deleted) OR c.deleted = false) "
                "ORDER BY c.updatedAtUtc DESC"
            )
            params = [{"name": "@campus", "value": campus}]
        else:
            query = (
                "SELECT * FROM c WHERE c.campus = @campus "
                "AND (c.createdBy = @username OR c.assignedTo = @username) "
                "AND (NOT IS_DEFINED(c.deleted) OR c.deleted = false) "
                "ORDER BY c.updatedAtUtc DESC"
            )
            params = [
                {"name": "@campus", "value": campus},
                {"name": "@username", "value": username},
            ]
        return self.tickets.query_items(query, params)

    def update_ticket(self, ticket_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        ticket = self.get_ticket(ticket_id)
        ticket.update(updates)
        ticket["updatedAtUtc"] = updates.get("updatedAtUtc") or utc_now_iso()
        try:
            return self.tickets.upsert_item(ticket, ticket["campus"])
        except CosmosHttpResponseError as exc:
            raise TicketRepositoryError(str(exc))

    def add_message(self, ticket_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        self.get_ticket(ticket_id)
        message.setdefault("id", generate_ticket_message_id())
        message["ticketId"] = ticket_id
        message.setdefault("deleted", False)
        try:
            created = self.messages.create_item(message)
            self.update_ticket(
                ticket_id,
                {
                    "lastMessageAtUtc": created.get("createdAtUtc"),
                    "lastMessagePreview": self._preview_message(created),
                },
            )
            return created
        except CosmosHttpResponseError as exc:
            raise TicketRepositoryError(str(exc))

    def list_messages(self, ticket_id: str) -> List[Dict[str, Any]]:
        self.get_ticket(ticket_id)
        query = (
            "SELECT * FROM c WHERE c.ticketId = @ticketId "
            "AND (NOT IS_DEFINED(c.deleted) OR c.deleted = false) "
            "ORDER BY c.createdAtUtc ASC"
        )
        params = [{"name": "@ticketId", "value": ticket_id}]
        return self.messages.query_items(query, params)

    def add_system_message(
        self,
        ticket_id: str,
        sender_id: str,
        sender_name: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.add_message(
            ticket_id,
            {
                "id": generate_ticket_message_id(),
                "ticketId": ticket_id,
                "senderId": sender_id,
                "senderRole": "administrador",
                "senderName": sender_name,
                "message": message,
                "createdAtUtc": utc_now_iso(),
                "readAtUtc": None,
                "attachmentUrl": None,
                "deleted": False,
                "metadata": metadata or {"messageType": "system"},
            },
        )

    def close_ticket(self, ticket_id: str, closed_by: str) -> Dict[str, Any]:
        now = utc_now_iso()
        return self.update_ticket(
            ticket_id,
            {
                "estado": TicketEstado.CERRADO.value,
                "closedAtUtc": now,
                "closedBy": closed_by,
                "updatedAtUtc": now,
            },
        )

    @staticmethod
    def _preview_message(message: Dict[str, Any]) -> str:
        text = str(message.get("message") or "").strip()
        if len(text) <= 120:
            return text
        return f"{text[:117]}..."
