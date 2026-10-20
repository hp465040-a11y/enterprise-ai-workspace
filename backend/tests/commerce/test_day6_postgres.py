"""Real PostgreSQL tests, independent of pytest and its global fixtures."""
import importlib.util
import os
import unittest
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, delete, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session, selectinload

from app.db.base import Base
from app.models.exception_case import ExceptionCase
from app.models.fulfillment_event import FulfillmentEvent
from app.models.order import Order


class Day6PostgresTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def database(self, mode):
        url = make_url(os.environ['DAY6_TEST_DATABASE_URL'])
        if url.drivername != 'postgresql+asyncpg' or url.database != 'ragforge_day6_test':
            raise RuntimeError('Day6 requires explicit ragforge_day6_test; business DB forbidden')
        engine = create_async_engine(url)
        schema = 'day6_test_' + uuid.uuid4().hex
        try:
            async with engine.connect() as conn:
                self.assertEqual(await conn.scalar(text('SELECT current_database()')), 'ragforge_day6_test')
                await conn.rollback()
                tx = await conn.begin()
                try:
                    await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                    await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                    def setup(sync):
                        metadata = MetaData()
                        names = ['organizations']
                        if mode == 'models':
                            names += ['orders', 'exception_cases', 'fulfillment_events']
                        for name in names:
                            Base.metadata.tables[name].to_metadata(metadata)
                        metadata.create_all(sync)
                        if mode == 'migration':
                            for filename in ('0002_commerce_core.py', '0003_fulfillment_investigation.py'):
                                path = Path(__file__).resolve().parents[2] / 'alembic/versions' / filename
                                spec = importlib.util.spec_from_file_location(filename, path)
                                module = importlib.util.module_from_spec(spec)
                                spec.loader.exec_module(module)
                                with Operations.context(MigrationContext.configure(sync)):
                                    module.upgrade()
                    await conn.run_sync(setup)
                    org, order = uuid.uuid4(), uuid.uuid4()
                    await conn.execute(insert(Base.metadata.tables['organizations']).values(
                        id=org, name='Day6 test', slug=uuid.uuid4().hex))
                    await conn.execute(insert(Order).values(
                        id=order, organization_id=org, platform='test-platform', store_key='test-store',
                        order_number='DAY6-' + uuid.uuid4().hex, currency='USD',
                        subtotal_amount=10, total_amount=10, ordered_at=datetime.now(UTC)))
                    yield conn, org, order
                finally:
                    await tx.rollback()
                self.assertFalse(await conn.scalar(text('SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:name)'), {'name':schema}))
                await conn.rollback()
        finally:
            await engine.dispose()

    def case(self, org, order, **changes):
        return dict(id=uuid.uuid4(), organization_id=org, order_id=order,
                    exception_type='shipment_delay', problem_description='Investigate',
                    opened_at=datetime.now(UTC), **changes)

    def event(self, org, order, **changes):
        values = dict(id=uuid.uuid4(), organization_id=org, order_id=order,
                      event_type='shipped', occurred_at=datetime.now(UTC),
                      source='test-source', description='Shipment fact')
        values.update(changes)
        return values

    async def reject(self, conn, statement, sqlstate):
        savepoint = await conn.begin_nested()
        try:
            with self.assertRaises(IntegrityError) as caught:
                await conn.execute(statement)
            self.assertEqual(caught.exception.orig.sqlstate, sqlstate)
        finally:
            await savepoint.rollback()
        self.assertEqual(await conn.scalar(text('SELECT 1')), 1)

    async def test_multiple_cases_events_defaults_and_orm_relationships(self):
        for mode in ('models', 'migration'):
            with self.subTest(mode=mode):
                async with self.database(mode) as (conn, org, order):
                    for _ in range(2):
                        await conn.execute(insert(ExceptionCase).values(**self.case(org, order)))
                        await conn.execute(insert(FulfillmentEvent).values(**self.event(org, order)))
                    def check(sync):
                        with Session(sync, join_transaction_mode='create_savepoint') as session:
                            row = session.execute(select(Order).where(Order.id == order).options(
                                selectinload(Order.exception_cases), selectinload(Order.fulfillment_events))).scalar_one()
                            self.assertEqual(len(row.exception_cases), 2)
                            self.assertEqual(len(row.fulfillment_events), 2)
                            for case in row.exception_cases:
                                self.assertIs(case.order, row)
                                self.assertEqual(case.status, 'open')
                                self.assertEqual(case.evidence_event_ids, [])
                                self.assertIsNotNone(case.created_at)
                                self.assertIsNotNone(case.updated_at)
                            for event in row.fulfillment_events:
                                self.assertIs(event.order, row)
                                self.assertIsNotNone(event.created_at)
                    await conn.run_sync(check)

    async def test_server_defaults_without_orm_defaults(self):
        for mode in ('models', 'migration'):
            with self.subTest(mode=mode):
                async with self.database(mode) as (conn, org, order):
                    await conn.execute(text('INSERT INTO exception_cases (id, organization_id, order_id, exception_type, problem_description, opened_at) VALUES (:id,:org,:ord,\'other\',\'Test\',now())'), {'id':uuid.uuid4(),'org':org,'ord':order})
                    row = (await conn.execute(text('SELECT status,evidence_event_ids,created_at,updated_at FROM exception_cases'))).one()
                    self.assertEqual(row.status, 'open')
                    self.assertEqual(row.evidence_event_ids, [])
                    self.assertIsNotNone(row.created_at)
                    self.assertIsNotNone(row.updated_at)

    async def test_case_closed_constraint(self):
        for mode in ('models', 'migration'):
            with self.subTest(mode=mode):
                async with self.database(mode) as (conn, org, order):
                    for changes in (
                        {'status': 'closed'},
                        {'status': 'closed', 'closed_at': datetime.now(UTC)},
                        {'status': 'closed', 'conclusion': 'Evidence reviewed'},
                        {'status': 'closed', 'closed_at': datetime.now(UTC), 'conclusion': ' '},
                    ):
                        await self.reject(conn, insert(ExceptionCase).values(**self.case(org,order,**changes)), '23514')
                    await conn.execute(insert(ExceptionCase).values(**self.case(org,order,status='closed',closed_at=datetime.now(UTC),conclusion='Evidence reviewed')))

    async def test_promise_time_constraint(self):
        for mode in ('models', 'migration'):
            with self.subTest(mode=mode):
                async with self.database(mode) as (conn, org, order):
                    for kind in ('shipment_promised', 'delivery_promised'):
                        await self.reject(conn, insert(FulfillmentEvent).values(**self.event(org,order,event_type=kind)), '23514')
                        await conn.execute(insert(FulfillmentEvent).values(**self.event(org,order,event_type=kind,expected_at=datetime.now(UTC))))
                    await self.reject(conn, insert(FulfillmentEvent).values(**self.event(org,order,expected_at=datetime.now(UTC))), '23514')

    async def test_external_event_deduplication(self):
        for mode in ('models', 'migration'):
            with self.subTest(mode=mode):
                async with self.database(mode) as (conn, org, order):
                    await conn.execute(insert(FulfillmentEvent).values(**self.event(org,order,external_event_id='event-1')))
                    await self.reject(conn, insert(FulfillmentEvent).values(**self.event(org,order,external_event_id='event-1')), '23505')
                    await conn.execute(insert(FulfillmentEvent).values(**self.event(org,order,external_event_id='event-1',source='other-source')))
                    for _ in range(2):
                        await conn.execute(insert(FulfillmentEvent).values(**self.event(org,order)))

    async def test_foreign_keys_and_order_delete_restriction(self):
        for mode in ('models', 'migration'):
            with self.subTest(mode=mode):
                async with self.database(mode) as (conn, org, order):
                    for model, factory in ((ExceptionCase,self.case),(FulfillmentEvent,self.event)):
                        await self.reject(conn, insert(model).values(**factory(org,uuid.uuid4())), '23503')
                        await self.reject(conn, insert(model).values(**factory(uuid.uuid4(),order)), '23503')
                    await conn.execute(insert(ExceptionCase).values(**self.case(org,order)))
                    await self.reject(conn, delete(Order).where(Order.id == order), '23503')
                    await conn.execute(delete(ExceptionCase))
                    await conn.execute(insert(FulfillmentEvent).values(**self.event(org,order)))
                    await self.reject(conn, delete(Order).where(Order.id == order), '23503')
