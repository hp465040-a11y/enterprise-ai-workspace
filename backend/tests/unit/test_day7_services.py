"""Service unit tests: SQL contracts and deterministic comparison boundaries."""
import unittest
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.db.base import Base  # noqa: F401 -- register relationship targets
from app.core.exceptions import NotFoundError, ValidationAppError
from app.services.exception_service import get_exception_case
from app.services.fulfillment_service import analyze_fulfillment

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def event(kind, occurred=NOW - timedelta(hours=2), expected=None, tracking='parcel-a'):
    return SimpleNamespace(id=uuid4(), event_type=kind, occurred_at=occurred,
                           expected_at=expected, tracking_number=tracking,
                           created_at=NOW, source='test', external_event_id=None, description='Fact')


class Day7ServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.org, self.order = uuid4(), uuid4()
        self.db = MagicMock()
        self.db.execute = AsyncMock(return_value=MagicMock())

    def returns(self, events, found=True):
        order = MagicMock()
        order.scalar_one_or_none.return_value = object() if found else None
        rows = MagicMock()
        rows.scalars.return_value.all.return_value = events
        self.db.execute.side_effect = [order, rows]

    async def analyze(self, events, as_of=NOW):
        self.returns(events)
        return await analyze_fulfillment(self.db, organization_id=self.org, order_id=self.order, as_of=as_of)

    async def test_case_success_sql_scope_and_no_writes(self):
        case = object()
        self.db.execute.return_value.scalar_one_or_none.return_value = case
        case_id = uuid4()
        self.assertIs(await get_exception_case(self.db, organization_id=self.org, case_id=case_id), case)
        compiled = self.db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
        self.assertEqual(compiled.params, {'organization_id_1': self.org, 'id_1': case_id})
        self.db.commit.assert_not_called()
        self.db.flush.assert_not_called()

    async def test_case_not_found(self):
        self.db.execute.return_value.scalar_one_or_none.return_value = None
        with self.assertRaises(NotFoundError):
            await get_exception_case(self.db, organization_id=self.org, case_id=uuid4())

    async def test_order_not_found(self):
        self.returns([], found=False)
        with self.assertRaises(NotFoundError):
            await analyze_fulfillment(self.db, organization_id=self.org, order_id=self.order, as_of=NOW)
        self.assertEqual(self.db.execute.await_count, 1)

    async def test_event_query_scope_cutoff_order_and_no_writes(self):
        result = await self.analyze([])
        queries = [call.args[0].compile(dialect=postgresql.dialect()) for call in self.db.execute.call_args_list]
        self.assertEqual(queries[0].params, {'organization_id_1':self.org, 'id_1':self.order})
        self.assertEqual(queries[1].params, {'organization_id_1':self.org, 'order_id_1':self.order, 'occurred_at_1':NOW})
        self.assertIn('ORDER BY fulfillment_events.occurred_at, fulfillment_events.created_at, fulfillment_events.id', str(queries[1]))
        self.assertEqual(result['timeline'], [])
        self.assertEqual(result['shipment']['status'], 'unknown')
        self.db.commit.assert_not_called()
        self.db.flush.assert_not_called()

    async def test_on_time_late_and_equal_deadline(self):
        for promise_type, actual_type, key in (
            ('shipment_promised','shipped','shipment'), ('delivery_promised','delivered','delivery')):
            for seconds, status in ((-1,'on_time'),(0,'on_time'),(1,'late')):
                with self.subTest(stage=key, seconds=seconds):
                    promise = event(promise_type, NOW-timedelta(hours=3), NOW-timedelta(hours=1))
                    actual = event(actual_type, promise.expected_at+timedelta(seconds=seconds))
                    result = await self.analyze([promise,actual])
                    comparison = result[key]
                    self.assertEqual(comparison['status'], status)
                    self.assertEqual(comparison['difference_seconds'], seconds)
                    self.assertEqual(comparison['scope'], 'shipment')
                    self.assertEqual(comparison['tracking_number'], 'parcel-a')
                    self.assertEqual(comparison['evidence_event_ids'], [promise.id,actual.id])
                    self.assertEqual(result['whole_order_completion'], 'unknown')

    async def test_equivalent_timezones(self):
        promise = event('delivery_promised', NOW-timedelta(hours=3), NOW-timedelta(hours=1))
        actual = event('delivered', promise.expected_at.astimezone(timezone(timedelta(hours=8))))
        self.assertEqual((await self.analyze([promise,actual]))['delivery']['difference_seconds'], 0)

    async def test_naive_as_of_rejected_before_query(self):
        with self.assertRaises(ValidationAppError):
            await analyze_fulfillment(self.db, organization_id=self.org, order_id=self.order, as_of=NOW.replace(tzinfo=None))
        self.db.execute.assert_not_awaited()

    async def test_missing_completion_deadline_is_observation_only(self):
        for expected, exceeded in ((NOW-timedelta(seconds=1),True),(NOW,False),(NOW+timedelta(seconds=1),False)):
            with self.subTest(expected=expected):
                result = await self.analyze([event('shipment_promised', NOW-timedelta(hours=2), expected)])
                comparison = result['shipment']
                self.assertEqual(comparison['status'], 'unknown')
                self.assertEqual(comparison['reason'], 'completion_not_observed')
                self.assertEqual(comparison['deadline_exceeded'], exceeded)
                self.assertFalse(comparison['completion_observed'])

    async def test_missing_promise_and_failure_retained(self):
        failure = event('delivery_failed')
        result = await self.analyze([failure,event('delivered')])
        self.assertEqual(result['delivery']['reason'], 'missing_promise')
        self.assertIn(failure.id,result['evidence_event_ids'])

    async def test_ambiguous_scope_and_conflicts_unknown(self):
        promise = event('shipment_promised', NOW-timedelta(hours=3), NOW-timedelta(hours=1))
        actual = event('shipped')
        cases = [
            ([promise,promise,actual],'multiple_candidates'),
            ([promise,actual,actual],'multiple_candidates'),
            ([promise,event('shipped',tracking='parcel-b')],'tracking_mismatch'),
            ([promise,event('shipped',tracking=None)],'tracking_mismatch'),
            ([event('shipment_promised',expected=NOW,tracking=None),event('shipped',tracking=None)],'unspecified_scope'),
            ([event('shipment_promised',expected=NOW,tracking='   '),event('shipped',tracking='   ')],'unspecified_scope'),
            ([promise,event('shipped',NOW-timedelta(hours=4))],'time_conflict'),
            ([event('shipment_promised',NOW-timedelta(hours=1),NOW-timedelta(hours=2)),actual],'time_conflict'),
        ]
        for events,reason in cases:
            with self.subTest(reason=reason):
                result=await self.analyze(events)
                self.assertEqual(result['shipment']['status'],'unknown')
                self.assertEqual(result['shipment']['reason'],reason)

    async def test_database_errors_propagate(self):
        for function, kwargs in (
            (get_exception_case,{'case_id':uuid4()}),
            (analyze_fulfillment,{'order_id':self.order,'as_of':NOW})):
            error=ConnectionError('Database unavailable')
            self.db.execute.side_effect=error
            with self.assertRaises(ConnectionError) as caught:
                await function(self.db,organization_id=self.org,**kwargs)
            self.assertIs(caught.exception,error)
