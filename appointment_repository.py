import os
import uuid
from typing import Any, Dict, List, Optional

from azure.cosmos.exceptions import CosmosHttpResponseError

from appointment_models import ACTIVE_APPOINTMENT_STATUSES, utc_now_iso
from cosmos_helper import CosmosDBHelper


class AppointmentNotFoundError(Exception):
    pass


class AppointmentRepositoryError(Exception):
    pass


def generate_appointment_id() -> str:
    return f"appt_{uuid.uuid4().hex}"


class CosmosAppointmentRepository:
    def __init__(self, appointments_helper: Optional[CosmosDBHelper] = None):
        self.appointments = appointments_helper or CosmosDBHelper(
            os.environ.get("COSMOS_CONTAINER_APPOINTMENTS", "appointments"),
            os.environ.get("COSMOS_PK_APPOINTMENTS", "/student/matricula"),
        )

    def create_appointment(self, appointment: Dict[str, Any]) -> Dict[str, Any]:
        appointment.setdefault("id", generate_appointment_id())
        appointment.setdefault("type", "appointment")
        try:
            return self.appointments.create_item(appointment)
        except CosmosHttpResponseError as exc:
            raise AppointmentRepositoryError(str(exc))

    def get_appointment(self, appointment_id: str) -> Dict[str, Any]:
        query = "SELECT * FROM c WHERE c.id = @id AND c.type = 'appointment'"
        params = [{"name": "@id", "value": appointment_id}]
        results = self.appointments.query_items(query, params)
        if not results:
            raise AppointmentNotFoundError(appointment_id)
        return results[0]

    def list_appointments(self, filters: Optional[Dict[str, Optional[str]]] = None) -> List[Dict[str, Any]]:
        filters = filters or {}
        clauses = ["c.type = 'appointment'"]
        params = []

        simple_fields = {
            "status": "status",
            "area": "area",
            "priority": "priority",
            "matricula": "student.matricula",
            "campus": "student.campus",
        }
        for filter_name, field_name in simple_fields.items():
            value = filters.get(filter_name)
            if value:
                param_name = f"@{filter_name}"
                clauses.append(f"c.{field_name} = {param_name}")
                params.append({"name": param_name, "value": value})

        query = f"SELECT * FROM c WHERE {' AND '.join(clauses)} ORDER BY c.updated_at DESC"
        return self.appointments.query_items(query, params)

    def update_appointment(self, appointment_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        appointment = self.get_appointment(appointment_id)
        appointment.update(updates)
        appointment["updated_at"] = updates.get("updated_at") or utc_now_iso()
        partition_value = str((appointment.get("student") or {}).get("matricula") or appointment_id)
        try:
            return self.appointments.upsert_item(appointment, partition_value)
        except CosmosHttpResponseError as exc:
            raise AppointmentRepositoryError(str(exc))

    def has_active_duplicate(self, matricula: str, area: str, exclude_id: Optional[str] = None) -> bool:
        query = (
            "SELECT VALUE COUNT(1) FROM c WHERE c.type = 'appointment' "
            "AND c.student.matricula = @matricula AND c.area = @area "
            "AND ARRAY_CONTAINS(@active, c.status)"
        )
        params = [
            {"name": "@matricula", "value": matricula},
            {"name": "@area", "value": area},
            {"name": "@active", "value": list(ACTIVE_APPOINTMENT_STATUSES)},
        ]
        if exclude_id:
            query += " AND c.id != @exclude_id"
            params.append({"name": "@exclude_id", "value": exclude_id})
        result = self.appointments.query_items(query, params)
        return bool(result and int(result[0]) > 0)
