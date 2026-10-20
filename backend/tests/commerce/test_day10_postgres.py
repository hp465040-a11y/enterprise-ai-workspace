"""Tool -> Service -> real PG, using D8's guarded rollback-only lifecycle."""
import json
import unittest
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession
from test_day8_postgres import OBSERVED, Day8PostgresTests

from app.ai.tools.investigation_tools import create_investigation_tools
from app.core.exceptions import ValidationAppError
from app.db.base import Base
from app.models.exception_case import ExceptionCase
from app.models.fulfillment_event import FulfillmentEvent
from app.models.inventory_record import InventoryRecord
from app.models.order import Order
from app.services.fulfillment_service import get_fulfillment_events


class Day10PostgresTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_tools_tenants_observations_cutoff_and_read_only(self):
        helper = Day8PostgresTests()
        for mode in ("models", "migration"):
            with self.subTest(mode=mode):
                async with helper.database(mode) as (conn, org, order, day6, _):
                    other, other_order = uuid4(), uuid4()
                    await conn.execute(insert(Base.metadata.tables["organizations"]).values(
                        id=other, name="Other", slug=uuid4().hex,
                    ))
                    await conn.execute(insert(Order).values(
                        id=other_order, organization_id=other, platform="test", store_key="test",
                        order_number="other", currency="USD", subtotal_amount=0,
                        total_amount=0, ordered_at=OBSERVED,
                    ))
                    case = day6.case(org, order)
                    await conn.execute(insert(ExceptionCase).values(**case))
                    await conn.execute(insert(InventoryRecord).values(**helper.record(
                        org, on_hand_quantity=2, reserved_quantity=5,
                    )))
                    await conn.execute(insert(InventoryRecord).values(**helper.record(other, on_hand_quantity=99)))
                    async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint") as db:
                        tools = {t.name: t for t in create_investigation_tools(db, organization_id=org)}
                        events = tools["get_fulfillment_events"]
                        self.assertEqual((await events.ainvoke({"order_id": str(order)}))["events"], [])
                        self.assertEqual((await events.ainvoke({"order_id": str(uuid4())}))["status"], "not_found")
                        # Reverse insertion and tied occurred_at exercise all sort keys.
                        rows = [day6.event(org, order, id=UUID(int=i), occurred_at=OBSERVED,
                                           created_at=OBSERVED + timedelta(seconds=created))
                                for i, created in ((3, 1), (2, 0), (1, 0))]
                        rows += [day6.event(org, order, occurred_at=OBSERVED + timedelta(seconds=1)),
                                 day6.event(other, order, occurred_at=OBSERVED),
                                 day6.event(other, other_order, occurred_at=OBSERVED)]
                        for row in rows:
                            await conn.execute(insert(FulfillmentEvent).values(**row))
                        result = await events.ainvoke({"order_id": str(order), "as_of": OBSERVED.isoformat()})
                        self.assertEqual([r["event_id"] for r in result["events"]], [str(UUID(int=i)) for i in (1, 2, 3)])
                        self.assertEqual(len((await events.ainvoke({"order_id": str(order)}))["events"]), 4)
                        json.dumps(result)
                        inventory = await tools["get_inventory_status"].ainvoke({"sku": " Sku-A "})
                        self.assertEqual(inventory["inventory"]["available_quantity"], -3)
                        self.assertIsInstance(inventory["inventory"]["observed_at"], str)
                        self.assertEqual((await tools["get_inventory_status"].ainvoke({"sku": "missing"}))["status"], "not_found")
                        args = [{"case_id": str(case["id"])},
                                {"order_id": str(order), "as_of": OBSERVED.isoformat()},
                                {"sku": "Sku-A"}, {"order_id": str(order)}]
                        foreign = create_investigation_tools(db, organization_id=uuid4())
                        for tool, values in zip(foreign, args, strict=True):
                            self.assertEqual((await tool.ainvoke(values))["status"], "not_found")
                        self.assertEqual((await events.ainvoke({"order_id": str(other_order)}))["status"], "not_found")
                        with self.assertRaises(ValidationAppError):
                            await get_fulfillment_events(db, organization_id=org, order_id=order,
                                                         as_of=OBSERVED.replace(tzinfo=None))
                        # PG disallows writes; pending ORM objects must not autoflush.
                        await conn.execute(text("SET LOCAL transaction_read_only = on"))
                        pending = InventoryRecord(**helper.record(org, sku="PENDING"))
                        db.add(pending)
                        for tool, values in zip(tools.values(), args, strict=True):
                            result = await tool.ainvoke(values)
                            self.assertEqual(result["status"], "found")
                            json.dumps(result)
                        self.assertIn(pending, db.new)
