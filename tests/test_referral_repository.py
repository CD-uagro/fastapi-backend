import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from azure.cosmos.exceptions import CosmosHttpResponseError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("COSMOS_URL", "https://localhost:8081")
os.environ.setdefault("COSMOS_KEY", "test-key")
os.environ.setdefault("COSMOS_DB", "test-db")

import referral_repository


class _FakeContainer:
    def __init__(self, *, missing=False):
        self.missing = missing
        self.read_called = False

    def read(self):
        self.read_called = True
        if self.missing:
            raise CosmosHttpResponseError(status_code=404, message="not found")
        return {"id": "referrals"}


class _FakeDatabase:
    def __init__(self, helper):
        self.helper = helper
        self.created = []

    def create_container(self, *, id, partition_key):
        self.created.append((id, partition_key))
        self.helper.container = _FakeContainer(missing=False)
        return self.helper.container

    def get_container_client(self, name):
        return self.helper.container


class _FakeCosmosDBHelper:
    instances = []

    def __init__(self, container_name, partition_key):
        self.container_name = container_name
        self.partition_key = partition_key
        self.container = _FakeContainer(missing=_FakeCosmosDBHelper.missing)
        self.database = _FakeDatabase(self)
        _FakeCosmosDBHelper.instances.append(self)


class ReferralRepositoryCosmosTests(unittest.TestCase):
    def setUp(self):
        _FakeCosmosDBHelper.instances = []
        _FakeCosmosDBHelper.missing = False

    def test_referrals_helper_uses_expected_container_and_pk(self):
        with patch.object(referral_repository, "CosmosDBHelper", _FakeCosmosDBHelper):
            helper = referral_repository._build_referrals_helper()

        self.assertEqual(helper.container_name, "referrals")
        self.assertEqual(helper.partition_key, "/student/matricula")
        self.assertTrue(helper.container.read_called)
        self.assertEqual(helper.database.created, [])

    def test_referrals_helper_creates_missing_container(self):
        _FakeCosmosDBHelper.missing = True
        with patch.object(referral_repository, "CosmosDBHelper", _FakeCosmosDBHelper):
            helper = referral_repository._build_referrals_helper()

        self.assertEqual(len(helper.database.created), 1)
        container_name, partition_key = helper.database.created[0]
        self.assertEqual(container_name, "referrals")
        self.assertEqual(partition_key.path, "/student/matricula")


if __name__ == "__main__":
    unittest.main()
