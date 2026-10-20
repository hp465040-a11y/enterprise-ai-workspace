"""Metadata and offline migration tests; never connect to a database."""

import importlib.util
import io
import unittest
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db.base import Base
from app.models.exception_case import ExceptionCase, ExceptionCaseStatus, ExceptionType
from app.models.fulfillment_event import FulfillmentEvent, FulfillmentEventType
from app.models.order import Order


class FulfillmentModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configure_mappers()
        path = Path(__file__).resolve().parents[2] / "alembic/versions/0003_fulfillment_investigation.py"
        spec = importlib.util.spec_from_file_location("fulfillment_migration", path)
        cls.migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.migration)

    def test_exact_columns_and_registration(self):
        self.assertEqual(set(ExceptionCase.__table__.columns.keys()), {
            "id", "organization_id", "order_id", "exception_type", "status",
            "problem_description", "conclusion", "evidence_event_ids", "opened_at",
            "closed_at", "created_at", "updated_at",
        })
        self.assertEqual(set(FulfillmentEvent.__table__.columns.keys()), {
            "id", "organization_id", "order_id", "event_type", "occurred_at",
            "expected_at", "source", "external_event_id", "tracking_number", "description", "created_at",
        })
        for model in (ExceptionCase, FulfillmentEvent):
            self.assertIs(Base.metadata.tables[model.__tablename__], model.__table__)
            for column in model.__table__.columns:
                if column.name.endswith("_at"):
                    self.assertTrue(column.type.timezone)
            for fk in model.__table__.foreign_keys:
                self.assertEqual(fk.ondelete, "RESTRICT")

    def test_bidirectional_order_relationships_preserve_deletion_policy(self):
        for name, model in (("exception_cases", ExceptionCase), ("fulfillment_events", FulfillmentEvent)):
            relation = Order.__mapper__.relationships[name]
            self.assertIs(relation.mapper.class_, model)
            self.assertEqual(relation.back_populates, "order")
            self.assertEqual(relation.passive_deletes, "all")
            self.assertNotIn("delete", relation.cascade)
            self.assertEqual(model.__mapper__.relationships["order"].back_populates, name)

    def test_case_array_defaults_and_no_order_uniqueness(self):
        table = ExceptionCase.__table__
        column = table.c.evidence_event_ids
        self.assertIsInstance(column.type, postgresql.ARRAY)
        self.assertIsInstance(column.type.item_type, postgresql.UUID)
        first = column.default.arg(None)
        second = column.default.arg(None)
        first.append("example")
        self.assertEqual(second, [])
        self.assertEqual(str(column.server_default.arg), "'{}'::uuid[]")
        self.assertFalse(any(isinstance(c, UniqueConstraint) for c in table.constraints))
        self.assertFalse(any(i.unique for i in table.indexes))

    def test_enum_values_are_covered_by_check_constraints(self):
        for model, enum, name in (
            (ExceptionCase, ExceptionType, "ck_exception_cases_type"),
            (ExceptionCase, ExceptionCaseStatus, "ck_exception_cases_status"),
            (FulfillmentEvent, FulfillmentEventType, "ck_fulfillment_events_type"),
        ):
            constraint = next(c for c in model.__table__.constraints if c.name == name)
            for member in enum:
                self.assertIn(f"'{member.value}'", str(constraint.sqltext))

    def test_external_event_deduplication_scope(self):
        index = next(i for i in FulfillmentEvent.__table__.indexes if i.unique)
        self.assertEqual([c.name for c in index.columns],
                         ["organization_id", "order_id", "source", "external_event_id"])
        self.assertEqual(str(index.dialect_options["postgresql"]["where"]), "external_event_id IS NOT NULL")

    def test_migration_matches_model_ddl_and_rolls_back_only_new_tables(self):
        self.assertEqual(self.migration.down_revision, "0002_commerce_core")
        buffer = io.StringIO()
        context = MigrationContext.configure(dialect_name="postgresql", opts={
            "as_sql": True, "output_buffer": buffer,
        })
        with Operations.context(context):
            self.migration.upgrade()
        sql = buffer.getvalue()
        dialect = postgresql.dialect()
        for model in (ExceptionCase, FulfillmentEvent):
            table = model.__table__
            # Compare independent migration snapshot to ORM definitions, ignoring column order.
            ddl = str(CreateTable(table).compile(dialect=dialect))
            for line in ddl.splitlines():
                line = line.strip().rstrip(",")
                if line and not line.startswith("CREATE TABLE") and line != ")":
                    self.assertIn(line, sql)
            for index in table.indexes:
                self.assertIn(str(CreateIndex(index).compile(dialect=dialect)), sql)
        self.assertEqual(sql.count("CREATE TABLE"), 2)
        self.assertNotIn("ALTER TABLE", sql)
        buffer.seek(0)
        buffer.truncate()
        with Operations.context(context):
            self.migration.downgrade()
        self.assertEqual(buffer.getvalue().strip(),
                         "DROP TABLE fulfillment_events;\n\nDROP TABLE exception_cases;")


if __name__ == "__main__":
    unittest.main()
