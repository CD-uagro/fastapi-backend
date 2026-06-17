import os
import uuid
from typing import Any, Dict, List, Optional

from azure.cosmos import PartitionKey
from azure.cosmos.exceptions import CosmosHttpResponseError
try:
    from azure.cosmos.exceptions import CosmosResourceNotFoundError
except ImportError:  # pragma: no cover - compatibility with older SDKs
    CosmosResourceNotFoundError = CosmosHttpResponseError

from cosmos_helper import CosmosDBHelper
from referral_models import utc_now_iso


class ReferralNotFoundError(Exception):
    pass


class ReferralRepositoryError(Exception):
    pass


def generate_referral_id() -> str:
    return f"ref_{uuid.uuid4().hex}"


def _is_not_found_error(exc: CosmosHttpResponseError) -> bool:
    return getattr(exc, "status_code", None) == 404


def _build_referrals_helper() -> CosmosDBHelper:
    container_name = os.environ.get("COSMOS_CONTAINER_REFERRALS", "referrals")
    partition_key = os.environ.get("COSMOS_PK_REFERRALS", "/student/matricula")
    helper = CosmosDBHelper(container_name, partition_key)
    try:
        helper.container.read()
    except CosmosResourceNotFoundError:
        helper.database.create_container(
            id=container_name,
            partition_key=PartitionKey(path=partition_key),
        )
        helper.container = helper.database.get_container_client(container_name)
    except CosmosHttpResponseError as exc:
        if _is_not_found_error(exc):
            helper.database.create_container(
                id=container_name,
                partition_key=PartitionKey(path=partition_key),
            )
            helper.container = helper.database.get_container_client(container_name)
        else:
            raise
    return helper


class CosmosReferralRepository:
    def __init__(self, referrals_helper: Optional[CosmosDBHelper] = None):
        self.referrals = referrals_helper or _build_referrals_helper()

    def create_referral(self, referral: Dict[str, Any]) -> Dict[str, Any]:
        referral.setdefault("id", generate_referral_id())
        referral.setdefault("type", "referral")
        referral.setdefault("schemaVersion", 1)
        try:
            return self.referrals.create_item(referral)
        except CosmosHttpResponseError as exc:
            raise ReferralRepositoryError(str(exc))

    def get_referral(self, referral_id: str) -> Dict[str, Any]:
        query = "SELECT * FROM c WHERE c.id = @id AND c.type = 'referral'"
        params = [{"name": "@id", "value": referral_id}]
        results = self.referrals.query_items(query, params)
        if not results:
            raise ReferralNotFoundError(referral_id)
        return results[0]

    def list_referrals(self, filters: Optional[Dict[str, Optional[str]]] = None) -> List[Dict[str, Any]]:
        filters = filters or {}
        clauses = ["c.type = 'referral'"]
        params = []

        simple_fields = {
            "status": "status",
            "priority": "priority",
            "origin_area": "origin.area",
            "destination_area": "destination.area",
            "matricula": "student.matricula",
            "appointment_id": "appointmentId",
        }
        for filter_name, field_name in simple_fields.items():
            value = filters.get(filter_name)
            if value:
                param_name = f"@{filter_name}"
                clauses.append(f"c.{field_name} = {param_name}")
                params.append({"name": param_name, "value": value})

        student_name = filters.get("student_name")
        if student_name:
            clauses.append("CONTAINS(LOWER(c.student.nombre), @student_name)")
            params.append({"name": "@student_name", "value": str(student_name).lower()})

        query = f"SELECT * FROM c WHERE {' AND '.join(clauses)} ORDER BY c.updatedAt DESC"
        return self.referrals.query_items(query, params)

    def list_student_referrals(self, matricula: str) -> List[Dict[str, Any]]:
        query = (
            "SELECT * FROM c WHERE c.type = 'referral' "
            "AND c.student.matricula = @matricula "
            "ORDER BY c.createdAt DESC"
        )
        params = [{"name": "@matricula", "value": matricula}]
        return self.referrals.query_items(query, params)

    def list_pending_referrals(self, area: Optional[str] = None) -> List[Dict[str, Any]]:
        clauses = [
            "c.type = 'referral'",
            "ARRAY_CONTAINS(@pending_statuses, c.status)",
        ]
        params = [
            {"name": "@pending_statuses", "value": ["sent", "received", "accepted"]},
        ]
        if area:
            clauses.append("c.destination.area = @area")
            params.append({"name": "@area", "value": area})

        query = f"SELECT * FROM c WHERE {' AND '.join(clauses)} ORDER BY c.updatedAt DESC"
        return self.referrals.query_items(query, params)

    def update_referral(self, referral_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        referral = self.get_referral(referral_id)
        referral.update(updates)
        referral["updatedAt"] = updates.get("updatedAt") or utc_now_iso()
        partition_value = str((referral.get("student") or {}).get("matricula") or referral_id)
        try:
            return self.referrals.upsert_item(referral, partition_value)
        except CosmosHttpResponseError as exc:
            raise ReferralRepositoryError(str(exc))
