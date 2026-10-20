"""Day7 uses Day6's test-DB guard, random schema and rollback lifecycle."""
import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import test_day6_postgres as day6
from app.models.exception_case import ExceptionCase
from app.models.fulfillment_event import FulfillmentEvent
from app.core.exceptions import NotFoundError
from app.services.exception_service import get_exception_case
from app.services.fulfillment_service import analyze_fulfillment

NOW=datetime(2026,10,9,12,tzinfo=UTC)


class Day7PostgresTests(unittest.IsolatedAsyncioTestCase):
    async def test_scoped_case_and_order_lookup(self):
        helper=day6.Day6PostgresTests()
        for mode in ('models','migration'):
            with self.subTest(mode=mode):
                async with helper.database(mode) as (conn,org,order):
                    values=helper.case(org,order)
                    await conn.execute(insert(ExceptionCase).values(**values))
                    async with AsyncSession(bind=conn,join_transaction_mode='create_savepoint') as db:
                        case=await get_exception_case(db,organization_id=org,case_id=values['id'])
                        self.assertEqual(case.order_id,order)
                        for tenant,identifier in ((uuid4(),values['id']),(org,uuid4())):
                            with self.assertRaises(NotFoundError):
                                await get_exception_case(db,organization_id=tenant,case_id=identifier)
                        with self.assertRaises(NotFoundError):
                            await analyze_fulfillment(db,organization_id=uuid4(),order_id=order,as_of=NOW)
                        result=await analyze_fulfillment(db,organization_id=org,order_id=order,as_of=NOW)
                        self.assertEqual(result['timeline'],[])

    async def test_cutoff_stable_order_and_ship_scope(self):
        helper=day6.Day6PostgresTests()
        for mode in ('models','migration'):
            with self.subTest(mode=mode):
                async with helper.database(mode) as (conn,org,order):
                    rows=[
                        helper.event(org,order,event_type='shipment_promised',occurred_at=NOW-timedelta(hours=3),expected_at=NOW-timedelta(hours=1),tracking_number='A'),
                        helper.event(org,order,occurred_at=NOW-timedelta(hours=1),tracking_number='A'),
                        helper.event(org,order,event_type='delivered',occurred_at=NOW+timedelta(seconds=1)),
                        helper.event(uuid4(),order,occurred_at=NOW-timedelta(hours=2)),
                    ]
                    # A valid second tenant demonstrates SQL excludes mismatched event ownership.
                    from app.db.base import Base
                    await conn.execute(insert(Base.metadata.tables['organizations']).values(id=rows[3]['organization_id'],name='Other',slug=uuid4().hex))
                    for row in reversed(rows):
                        await conn.execute(insert(FulfillmentEvent).values(**row))
                    # Equal timestamps exercise created_at then UUID tie breakers.
                    for identifier,created in ((3,NOW),(2,NOW),(4,NOW-timedelta(seconds=1))):
                        await conn.execute(insert(FulfillmentEvent).values(**helper.event(org,order,id=UUID(int=identifier),event_type='in_transit',occurred_at=NOW,created_at=created)))
                    async with AsyncSession(bind=conn,join_transaction_mode='create_savepoint') as db:
                        result=await analyze_fulfillment(db,organization_id=org,order_id=order,as_of=NOW)
                        self.assertEqual(result['evidence_event_ids'],[rows[0]['id'],rows[1]['id'],UUID(int=4),UUID(int=2),UUID(int=3)])
                        self.assertEqual(result['shipment']['status'],'on_time')
                        self.assertEqual(result['shipment']['scope'],'shipment')
                        self.assertEqual(result['whole_order_completion'],'unknown')

    async def test_unknown_cases_with_real_records(self):
        helper=day6.Day6PostgresTests()
        for mode in ('models','migration'):
            with self.subTest(mode=mode):
                async with helper.database(mode) as (conn,org,order):
                    async with AsyncSession(bind=conn,join_transaction_mode='create_savepoint') as db:
                        await conn.execute(insert(FulfillmentEvent).values(**helper.event(org,order,event_type='delivery_promised',occurred_at=NOW-timedelta(hours=3),expected_at=NOW-timedelta(hours=1),tracking_number='A')))
                        result=await analyze_fulfillment(db,organization_id=org,order_id=order,as_of=NOW)
                        self.assertEqual(result['delivery']['reason'],'completion_not_observed')
                        self.assertTrue(result['delivery']['deadline_exceeded'])
                        await conn.execute(insert(FulfillmentEvent).values(**helper.event(org,order,event_type='delivered',occurred_at=NOW-timedelta(minutes=30),tracking_number='B')))
                        result=await analyze_fulfillment(db,organization_id=org,order_id=order,as_of=NOW)
                        self.assertEqual(result['delivery']['reason'],'tracking_mismatch')
                        await conn.execute(insert(FulfillmentEvent).values(**helper.event(org,order,event_type='delivery_promised',occurred_at=NOW-timedelta(hours=2),expected_at=NOW,tracking_number='A')))
                        result=await analyze_fulfillment(db,organization_id=org,order_id=order,as_of=NOW)
                        self.assertEqual(result['delivery']['reason'],'multiple_candidates')

    async def test_read_only_transaction_accepts_services_and_preserves_data(self):
        helper=day6.Day6PostgresTests()
        for mode in ('models','migration'):
            with self.subTest(mode=mode):
                async with helper.database(mode) as (conn,org,order):
                    values=helper.case(org,order)
                    await conn.execute(insert(ExceptionCase).values(**values))
                    before=(await conn.execute(select(ExceptionCase.__table__))).all()
                    async with AsyncSession(bind=conn,join_transaction_mode='create_savepoint') as db:
                        await get_exception_case(db,organization_id=org,case_id=values['id'])
                        await analyze_fulfillment(db,organization_id=org,order_id=order,as_of=NOW)

                    self.assertEqual((await conn.execute(select(ExceptionCase.__table__))).all(),before)
                    self.assertTrue(conn.in_transaction())
                    # Query operations are also enforced read-only by PostgreSQL.
                    await conn.execute(text('SET LOCAL transaction_read_only = on'))
                    async with AsyncSession(bind=conn,join_transaction_mode='create_savepoint') as db:
                        await get_exception_case(db,organization_id=org,case_id=values['id'])
                        await analyze_fulfillment(db,organization_id=org,order_id=order,as_of=NOW)

    async def test_comparison_boundaries_with_real_records(self):
        helper=day6.Day6PostgresTests()
        for mode in ('models','migration'):
            with self.subTest(mode=mode):
                async with helper.database(mode) as (conn,org,order):
                    def promise(**changes):
                        return helper.event(org,order,event_type='delivery_promised',
                                            occurred_at=NOW-timedelta(hours=3),
                                            expected_at=NOW-timedelta(hours=1),**changes)
                    def actual(**changes):
                        return helper.event(org,order,event_type='delivered',**changes)
                    scenarios=[
                        ([promise(tracking_number='A'),actual(tracking_number='A',occurred_at=NOW-timedelta(hours=1,seconds=1))],'on_time',None),
                        ([promise(tracking_number='A'),actual(tracking_number='A',occurred_at=NOW-timedelta(hours=1))],'on_time',None),
                        ([promise(tracking_number='A'),actual(tracking_number='A',occurred_at=NOW-timedelta(minutes=30))],'late',None),
                        ([promise(tracking_number=None),actual(tracking_number=None,occurred_at=NOW-timedelta(hours=1))],'unknown','unspecified_scope'),
                        ([promise(tracking_number='A'),actual(tracking_number='A',occurred_at=NOW-timedelta(hours=4))],'unknown','time_conflict'),
                        ([promise(tracking_number='A'),actual(tracking_number='A',occurred_at=NOW-timedelta(hours=1)),actual(tracking_number='A',occurred_at=NOW-timedelta(minutes=30))],'unknown','multiple_candidates'),
                        ([actual(tracking_number='A',occurred_at=NOW-timedelta(hours=1))],'unknown','missing_promise'),
                    ]
                    for rows,status,reason in scenarios:
                        with self.subTest(status=status,reason=reason):
                            savepoint=await conn.begin_nested()
                            try:
                                for row in rows:
                                    await conn.execute(insert(FulfillmentEvent).values(**row))
                                async with AsyncSession(bind=conn,join_transaction_mode='create_savepoint') as db:
                                    result=await analyze_fulfillment(db,organization_id=org,order_id=order,as_of=NOW)
                                    self.assertEqual(result['delivery']['status'],status)
                                    self.assertEqual(result['delivery']['reason'],reason)
                                    self.assertEqual(result['whole_order_completion'],'unknown')
                            finally:
                                await savepoint.rollback()
