"""Isolated PostgreSQL checks for order-linked allocation evidence."""

import importlib.util
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import test_day6_postgres as day6
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.investigation_report import evidence_contract
from app.ai.tools.investigation_tools import _json
from app.models.fulfillment_event import FulfillmentEvent
from app.models.order import Order
from app.services.fulfillment_service import analyze_fulfillment

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)
MIGRATION_PATH = Path(__file__).resolve().parents[2] / "alembic/versions/0008_order_allocation_evidence.py"


class OrderAllocationPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_and_migration_support_real_scoped_causal_read(self):
        helper = day6.Day6PostgresTests()
        for mode in ("models", "migration"):
            with self.subTest(mode=mode):
                async with helper.database(mode) as (conn, org, order):
                    if mode == "migration":
                        spec = importlib.util.spec_from_file_location("allocation_migration", MIGRATION_PATH)
                        migration = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(migration)
                        def upgrade(sync, module=migration):
                            with Operations.context(MigrationContext.configure(sync)):
                                module.upgrade()
                        await conn.run_sync(upgrade)
                    promise = helper.event(org, order, event_type="shipment_promised",
                                           occurred_at=NOW-timedelta(hours=4),
                                           expected_at=NOW-timedelta(hours=2), tracking_number="parcel-a")
                    shipped = helper.event(org, order, event_type="shipped",
                                           occurred_at=NOW-timedelta(hours=1), tracking_number="parcel-a")
                    failure = helper.event(org, order, event_type="inventory_allocation_failed",
                                           occurred_at=NOW-timedelta(hours=3), tracking_number="parcel-a",
                                           external_event_id="allocation-1")
                    attribution = helper.event(org, order, event_type="shipment_delay_attributed",
                                               occurred_at=NOW-timedelta(hours=1, minutes=30),
                                               tracking_number="parcel-a", external_event_id="attribution-1",
                                               caused_by_event_id=failure["id"])
                    for row in (promise, failure, attribution, shipped):
                        await conn.execute(insert(FulfillmentEvent).values(**row))
                    async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint") as db:
                        before = await analyze_fulfillment(db, organization_id=org, order_id=order,
                                                           as_of=NOW-timedelta(hours=2, minutes=30))
                        self.assertEqual(before["allocation"]["status"], "blocked")
                        self.assertEqual(before["allocation"]["causal_status"], "unknown")
                        result = await analyze_fulfillment(db, organization_id=org, order_id=order, as_of=NOW)
                        self.assertEqual(result["allocation"]["causal_status"], "linked_to_shipment_delay")
                        self.assertEqual(result["shipment"]["status"], "late")
                        self.assertEqual(evidence_contract([{
                            "tool": "analyze_fulfillment", "result": {"status": "found", "analysis": _json(result)},
                        }])["root_cause"], "inventory_allocation_blocked")
                        other_org, other_order = uuid4(), uuid4()
                        await conn.execute(insert(Order.__table__.metadata.tables["organizations"]).values(
                            id=other_org, name="Other", slug=uuid4().hex))
                        await conn.execute(insert(Order).values(
                            id=other_order, organization_id=other_org, platform="test", store_key="test",
                            order_number=uuid4().hex, currency="USD", subtotal_amount=10,
                            total_amount=10, ordered_at=NOW))
                        foreign = helper.event(other_org, other_order, event_type="inventory_allocation_failed",
                                               occurred_at=NOW-timedelta(hours=3), tracking_number="parcel-a",
                                               external_event_id="foreign-allocation")
                        await conn.execute(insert(FulfillmentEvent).values(**foreign))
                        for row in (
                            helper.event(other_org, other_order, event_type="shipment_promised",
                                         occurred_at=NOW-timedelta(hours=4),
                                         expected_at=NOW-timedelta(hours=2), tracking_number="parcel-a"),
                            helper.event(other_org, other_order, event_type="shipped",
                                         occurred_at=NOW-timedelta(hours=1), tracking_number="parcel-a"),
                            helper.event(other_org, other_order, event_type="shipment_delay_attributed",
                                         occurred_at=NOW-timedelta(hours=1, minutes=30),
                                         tracking_number="parcel-a", external_event_id="foreign-attribution",
                                         caused_by_event_id=failure["id"]),
                        ):
                            await conn.execute(insert(FulfillmentEvent).values(**row))
                        self.assertEqual((await analyze_fulfillment(
                            db, organization_id=other_org, order_id=other_order, as_of=NOW,
                        ))["allocation"]["causal_status"], "unknown")
                        self.assertEqual(await conn.scalar(text("SELECT current_database()")), "ragforge_day6_test")


if __name__ == "__main__":
    unittest.main()
