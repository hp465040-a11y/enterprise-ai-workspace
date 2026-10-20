"""Real inventory tests in Day6's guarded database, schemas and rollback lifecycle."""

import importlib.util
import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import test_day6_postgres as day6
from app.db.base import Base
from app.core.exceptions import NotFoundError
from app.models.inventory_record import InventoryRecord
from app.services.inventory_service import get_inventory_status

OBSERVED=datetime(2026,10,9,12,tzinfo=UTC)


class Day8PostgresTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def database(self,mode):
        helper=day6.Day6PostgresTests()
        # This validates the explicit database name before connecting and the
        # real identity after connecting. A business DB is never accepted.
        async with helper.database(mode) as (conn,org,order):
            path=Path(__file__).resolve().parents[2]/"alembic/versions/0004_inventory_record.py"
            spec=importlib.util.spec_from_file_location("day8_migration",path)
            migration=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            def setup(sync):
                if mode=="models":
                    InventoryRecord.__table__.create(sync)
                else:
                    with Operations.context(MigrationContext.configure(sync)):
                        migration.upgrade()
            await conn.run_sync(setup)
            yield conn,org,order,helper,migration

    def record(self,org,**changes):
        values=dict(id=uuid4(),organization_id=org,sku="Sku-A",on_hand_quantity=10,
                    reserved_quantity=3,observed_at=OBSERVED)
        values.update(changes)
        return values

    async def test_snapshot_query_defaults_and_quantity_boundaries(self):
        for mode in ("models","migration"):
            with self.subTest(mode=mode):
                async with self.database(mode) as (conn,org,_,helper,migration):
                    for sku,hand,reserved,available in (("NORMAL",10,3,7),("ZERO",0,0,0),("EQUAL",5,5,0),("OVER",2,5,-3)):
                        await conn.execute(insert(InventoryRecord).values(**self.record(org,sku=sku,on_hand_quantity=hand,reserved_quantity=reserved)))
                        async with AsyncSession(bind=conn,join_transaction_mode="create_savepoint") as db:
                            result=await get_inventory_status(db,organization_id=org,sku=" \t"+sku+"\n")
                            self.assertEqual(result["available_quantity"],available)
                            self.assertEqual(result["on_hand_quantity"],hand)
                            self.assertEqual(result["reserved_quantity"],reserved)
                            self.assertEqual(result["observed_at"],OBSERVED)
                            self.assertEqual(result["scope"],"organization_sku")
                    rows=(await conn.execute(select(InventoryRecord.__table__))).all()
                    self.assertEqual(len(rows),4)
                    self.assertTrue(all(r.created_at and r.updated_at for r in rows))

    async def test_tenant_scope_case_sensitivity_and_absence(self):
        for mode in ("models","migration"):
            with self.subTest(mode=mode):
                async with self.database(mode) as (conn,org,_,helper,migration):
                    other=uuid4()
                    await conn.execute(insert(Base.metadata.tables["organizations"]).values(id=other,name="Other",slug=uuid4().hex))
                    await conn.execute(insert(InventoryRecord).values(**self.record(org)))
                    await conn.execute(insert(InventoryRecord).values(**self.record(other,on_hand_quantity=20)))
                    await conn.execute(insert(InventoryRecord).values(**self.record(org,sku="sku-a",on_hand_quantity=30)))
                    async with AsyncSession(bind=conn,join_transaction_mode="create_savepoint") as db:
                        for tenant,sku,hand in ((org,"Sku-A",10),(other,"Sku-A",20),(org,"sku-a",30)):
                            result=await get_inventory_status(db,organization_id=tenant,sku=sku)
                            self.assertEqual(result["on_hand_quantity"],hand)
                        for tenant,sku in ((org,"MISSING"),(uuid4(),"Sku-A")):
                            with self.assertRaises(NotFoundError):
                                await get_inventory_status(db,organization_id=tenant,sku=sku)

    async def test_unique_sku_nonblank_canonical_and_nonnegative_constraints(self):
        for mode in ("models","migration"):
            with self.subTest(mode=mode):
                async with self.database(mode) as (conn,org,_,helper,migration):
                    await conn.execute(insert(InventoryRecord).values(**self.record(org)))
                    await helper.reject(conn,insert(InventoryRecord).values(**self.record(org)),"23505")
                    for sku in ("","   ","\t\n"," Sku-B","Sku-B "):
                        await helper.reject(conn,insert(InventoryRecord).values(**self.record(org,sku=sku)),"23514")
                    for changes in ({"on_hand_quantity":-1},{"reserved_quantity":-1}):
                        await helper.reject(conn,insert(InventoryRecord).values(**self.record(org,sku="OTHER",**changes)),"23514")
                    await helper.reject(conn,insert(InventoryRecord).values(**self.record(uuid4())),"23503")

    async def test_required_quantities_and_observed_time_have_no_default(self):
        for mode in ("models","migration"):
            with self.subTest(mode=mode):
                async with self.database(mode) as (conn,org,_,helper,migration):
                    for field in ("on_hand_quantity","reserved_quantity","observed_at"):
                        for omit in (True,False):
                            values=self.record(org)
                            if omit:
                                del values[field]
                            else:
                                values[field]=None
                            await helper.reject(conn,insert(InventoryRecord).values(**values),"23502")

    async def test_service_is_read_only_even_with_pending_session_objects(self):
        for mode in ("models","migration"):
            with self.subTest(mode=mode):
                async with self.database(mode) as (conn,org,_,helper,migration):
                    await conn.execute(insert(InventoryRecord).values(**self.record(org)))
                    before=(await conn.execute(select(InventoryRecord.__table__))).all()
                    await conn.execute(text("SET LOCAL transaction_read_only = on"))
                    async with AsyncSession(bind=conn,join_transaction_mode="create_savepoint") as db:
                        pending=InventoryRecord(**self.record(org,sku="PENDING"))
                        db.add(pending)
                        result=await get_inventory_status(db,organization_id=org,sku="Sku-A")
                        self.assertEqual(result["available_quantity"],7)
                        self.assertIn(pending,db.new)
                    self.assertEqual((await conn.execute(select(InventoryRecord.__table__))).all(),before)
                    self.assertTrue(conn.in_transaction())

    async def test_0004_downgrade_is_isolated_and_preserves_prior_tables(self):
        async with self.database("migration") as (conn,org,order,helper,migration):
            def downgrade(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    migration.downgrade()
            await conn.run_sync(downgrade)
            schema=await conn.scalar(text("SELECT current_schema()"))
            self.assertIsNone(await conn.scalar(text("SELECT to_regclass(:name)"),{"name":schema+".inventory_records"}))
            self.assertEqual(await conn.scalar(text("SELECT count(*) FROM orders WHERE id=:id"),{"id":order}),1)
            self.assertIsNotNone(await conn.scalar(text("SELECT to_regclass(:name)"),{"name":schema+".exception_cases"}))
            def upgrade(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    migration.upgrade()
            await conn.run_sync(upgrade)
            await conn.execute(insert(InventoryRecord).values(**self.record(org)))
            async with AsyncSession(bind=conn,join_transaction_mode="create_savepoint") as db:
                self.assertEqual((await get_inventory_status(db,organization_id=org,sku="Sku-A"))["available_quantity"],7)
