"""Inventory SQL contract, validation and quantity calculation tests."""

import io
import importlib.util
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Integer
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db.base import Base  # noqa: F401 -- register ORM relationships
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.inventory_record import InventoryRecord
from app.services.inventory_service import get_inventory_status


class InventoryServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.org = uuid4()
        self.db = MagicMock()
        self.result = MagicMock()
        self.db.execute = AsyncMock(return_value=self.result)
        self.observed = datetime(2026, 10, 9, 12, tzinfo=UTC)

    async def test_scoped_trimmed_case_sensitive_query_and_snapshot(self):
        self.result.scalar_one_or_none.return_value = SimpleNamespace(
            organization_id=self.org, sku="Sku-A", on_hand_quantity=10,
            reserved_quantity=3, observed_at=self.observed,
        )
        value = await get_inventory_status(self.db, organization_id=self.org, sku=" \tSku-A\n")
        self.assertEqual(value, {
            "scope":"organization_sku", "organization_id":self.org, "sku":"Sku-A",
            "on_hand_quantity":10, "reserved_quantity":3, "available_quantity":7,
            "observed_at":self.observed,
        })
        compiled = self.db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
        self.assertEqual(compiled.params, {"organization_id_1":self.org, "sku_1":"Sku-A"})
        self.db.no_autoflush.__enter__.assert_called_once()
        self.db.commit.assert_not_called()
        self.db.flush.assert_not_called()
        self.db.add.assert_not_called()

    async def test_zero_equal_and_negative_available_quantity(self):
        for on_hand, reserved, expected in ((0,0,0),(5,5,0),(2,5,-3),(0, 4, -4),):
            with self.subTest(on_hand=on_hand, reserved=reserved):
                self.result.scalar_one_or_none.return_value = SimpleNamespace(
                    organization_id=self.org, sku="SKU", on_hand_quantity=on_hand,
                    reserved_quantity=reserved, observed_at=self.observed,
                )
                value = await get_inventory_status(self.db, organization_id=self.org, sku="SKU")
                self.assertEqual(value["available_quantity"], expected)
                self.assertEqual(value["observed_at"], self.observed)

    async def test_missing_record_is_not_zero(self):
        self.result.scalar_one_or_none.return_value = None
        with self.assertRaises(NotFoundError) as caught:
            await get_inventory_status(self.db, organization_id=self.org, sku="missing")
        self.assertEqual(caught.exception.error_code, "not_found")

    async def test_invalid_sku_before_database_query(self):
        for sku in (None,123,""," \t\n ","A"*129):
            with self.subTest(sku=sku), self.assertRaises(ValidationAppError):
                await get_inventory_status(self.db, organization_id=self.org, sku=sku)
        self.db.execute.assert_not_awaited()

    async def test_database_error_propagates(self):
        for error in (ConnectionError("DB unavailable"),TimeoutError("DB timeout")):
            self.db.execute.side_effect = error
            with self.assertRaises(type(error)) as caught:
                await get_inventory_status(self.db, organization_id=self.org, sku="SKU")
            self.assertIs(caught.exception,error)


class InventoryMetadataTests(unittest.TestCase):
    def test_exact_columns_required_integer_quantities_and_no_defaults(self):
        table=InventoryRecord.__table__
        self.assertEqual(set(table.c.keys()), {"id","organization_id","sku","on_hand_quantity",
                         "reserved_quantity","observed_at","created_at","updated_at"})
        self.assertIs(Base.metadata.tables["inventory_records"],table)
        for name in ("on_hand_quantity","reserved_quantity","observed_at"):
            self.assertFalse(table.c[name].nullable)
            self.assertIsNone(table.c[name].default)
            self.assertIsNone(table.c[name].server_default)
        for name in ("on_hand_quantity","reserved_quantity"):
            self.assertIsInstance(table.c[name].type,Integer)
        self.assertTrue(table.c.observed_at.type.timezone)

    def test_independent_migration_matches_model_ddl(self):
        path=Path(__file__).resolve().parents[2]/"alembic/versions/0004_inventory_record.py"
        spec=importlib.util.spec_from_file_location("inventory_migration",path)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.down_revision,"0003_fulfillment_investigation")
        output=io.StringIO()
        context=MigrationContext.configure(dialect_name="postgresql",opts={"as_sql":True,"output_buffer":output})
        with Operations.context(context):
            module.upgrade()
        sql=output.getvalue()
        ddl=str(CreateTable(InventoryRecord.__table__).compile(dialect=postgresql.dialect()))
        for line in ddl.splitlines():
            line=line.strip().rstrip(",")
            if line and not line.startswith("CREATE TABLE") and line != ")":
                self.assertIn(line,sql)
        self.assertEqual(sql.count("CREATE TABLE"),1)
        self.assertNotIn("ALTER TABLE",sql)
        output.seek(0)
        output.truncate()
        with Operations.context(context):
            module.downgrade()
        self.assertEqual(output.getvalue().strip(),"DROP TABLE inventory_records;")
