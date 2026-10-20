"""Real PG lifecycle checks for counterfactual inventory and fault injection."""
import unittest

from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError
from test_day8_postgres import Day8PostgresTests

from app.models.inventory_record import InventoryRecord


class Day13PostgresTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_phase_rollback_allows_next_fixture_observation(self):
        helper = Day8PostgresTests()
        async with helper.database("migration") as (conn, org, _, _, _):
            await conn.execute(insert(InventoryRecord).values(**helper.record(org)))
            phase = await conn.begin_nested()
            await conn.execute(text("SET LOCAL transaction_read_only = on"))
            self.assertEqual(await conn.scalar(text("SHOW transaction_read_only")), "on")
            await phase.rollback()
            self.assertEqual(await conn.scalar(text("SHOW transaction_read_only")), "off")
            await conn.execute(update(InventoryRecord).where(InventoryRecord.organization_id == org).values(on_hand_quantity=99))
            self.assertEqual(await conn.scalar(select(InventoryRecord.on_hand_quantity)), 99)

    async def test_real_statement_timeout_is_failure_and_rollback_recovers(self):
        async with Day8PostgresTests().database("migration") as (conn, _, _, _, _):
            phase = await conn.begin_nested()
            try:
                await conn.execute(text("SET LOCAL transaction_read_only = on"))
                await conn.execute(text("SET LOCAL statement_timeout = '20ms'"))
                with self.assertRaises(DBAPIError) as caught:
                    await conn.execute(text("SELECT pg_sleep(0.2)"))
                self.assertEqual(caught.exception.orig.sqlstate, "57014")
            finally:
                await phase.rollback()
            self.assertEqual(await conn.scalar(text("SELECT 1")), 1)
