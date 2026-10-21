"""Typed order allocation evidence and conservative causal report boundaries."""

import json
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.ai.agents.investigation_report import evidence_contract, render_report, validate_report
from app.ai.tools.investigation_tools import _json
from app.services.fulfillment_service import analyze_fulfillment

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def event(kind, at, *, tracking="parcel-a", source="allocation-system", external=None, related=None,
          expected=None):
    return SimpleNamespace(
        id=uuid4(), event_type=kind, occurred_at=at, expected_at=expected,
        tracking_number=tracking, source=source, external_event_id=external,
        caused_by_event_id=related, description="Synthetic order evidence", created_at=NOW,
    )


class OrderAllocationCauseTests(unittest.IsolatedAsyncioTestCase):
    async def analyze(self, rows):
        with patch("app.services.fulfillment_service.get_fulfillment_events",
                   new_callable=AsyncMock, return_value=rows):
            return await analyze_fulfillment(object(), organization_id=uuid4(),
                                             order_id=uuid4(), as_of=NOW)

    def rows(self):
        promise = event("shipment_promised", NOW - timedelta(hours=4),
                        expected=NOW - timedelta(hours=2))
        shipped = event("shipped", NOW - timedelta(hours=1))
        failure = event("inventory_allocation_failed", NOW - timedelta(hours=3), external="alloc-1")
        attribution = event("shipment_delay_attributed", NOW - timedelta(hours=1, minutes=30),
                            external="cause-1", related=failure.id)
        return promise, shipped, failure, attribution

    @staticmethod
    def trace(analysis):
        return [{"tool": "analyze_fulfillment", "result": {"status": "found", "analysis": _json(analysis)}}]

    async def test_failure_record_confirms_block_but_not_delay_cause(self):
        promise, shipped, failure, _ = self.rows()
        analysis = await self.analyze([promise, failure, shipped])
        self.assertEqual(analysis["shipment"]["status"], "late")
        self.assertEqual(analysis["allocation"]["status"], "blocked")
        self.assertEqual(analysis["allocation"]["causal_status"], "unknown")
        trace = self.trace(analysis)
        contract = evidence_contract(trace)
        self.assertEqual(contract["root_cause"], "unknown")
        with self.assertRaises(ValueError):
            validate_report(json.dumps({**contract, "root_cause": "inventory_allocation_blocked"},
                                       default=str), trace)
        handoff = render_report(validate_report(json.dumps(contract, default=str), trace), trace)
        self.assertIn("分配失败已记录", handoff)
        self.assertIn("建议，尚未执行", handoff)

    async def test_explicit_link_to_same_late_shipment_supports_one_cause(self):
        rows = self.rows()
        analysis = await self.analyze(list(rows))
        allocation = analysis["allocation"]
        self.assertEqual(allocation["causal_status"], "linked_to_shipment_delay")
        self.assertEqual(allocation["linked_failure_event_id"], rows[2].id)
        self.assertEqual(allocation["attribution_event_id"], rows[3].id)
        trace = self.trace(analysis)
        contract = evidence_contract(trace)
        self.assertEqual(contract["root_cause"], "inventory_allocation_blocked")
        self.assertEqual(set(contract["evidence_event_ids"]), {str(row.id) for row in rows})
        with self.assertRaises(ValueError):
            validate_report(json.dumps({**contract, "root_cause": "unknown"}, default=str), trace)
        handoff = render_report(validate_report(json.dumps(contract, default=str), trace), trace)
        self.assertIn(str(rows[3].id), handoff)
        self.assertIn("发货延迟与库存分配受阻", handoff)
        self.assertIn("整单完成情况未知", handoff)
        incomplete = deepcopy(analysis)
        incomplete["allocation"]["failure_event_ids"] = []
        self.assertEqual(evidence_contract(self.trace(incomplete))["root_cause"], "unknown")

    async def test_bad_link_tracking_source_or_time_keeps_cause_unknown(self):
        for change in ("missing_reference", "wrong_tracking", "wrong_source", "late_failure",
                       "premature_attribution", "future_attribution", "ambiguous_link"):
            with self.subTest(change=change):
                promise, shipped, failure, attribution = self.rows()
                if change == "missing_reference":
                    attribution.caused_by_event_id = uuid4()
                elif change == "wrong_tracking":
                    attribution.tracking_number = "other-parcel"
                elif change == "wrong_source":
                    attribution.source = "other-system"
                elif change == "late_failure":
                    failure.occurred_at = promise.expected_at + timedelta(minutes=1)
                elif change == "premature_attribution":
                    attribution.occurred_at = promise.expected_at - timedelta(minutes=1)
                elif change == "future_attribution":
                    attribution.occurred_at = NOW + timedelta(minutes=1)
                rows = [promise, failure, attribution, shipped]
                if change == "ambiguous_link":
                    rows.append(event("shipment_delay_attributed", attribution.occurred_at,
                                      external="cause-2", related=failure.id))
                analysis = await self.analyze(rows)
                self.assertEqual(analysis["allocation"]["status"], "blocked")
                self.assertEqual(analysis["allocation"]["causal_status"], "unknown")
                self.assertEqual(evidence_contract(self.trace(analysis))["root_cause"], "unknown")


if __name__ == "__main__":
    unittest.main()
