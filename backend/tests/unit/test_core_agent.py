import json
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.core_agent import CoreAgentError, run_core_agent
from app.ai.llm.base import LLMToolCall, LLMToolResponse


class CoreAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.case, self.org, self.order = uuid4(), uuid4(), uuid4()
        self.now = datetime(2026, 10, 11, tzinfo=UTC)
        self.db = MagicMock(spec=AsyncSession)

    def response(self, name=None, args=None, identifier="1", outcome="insufficient_evidence"):
        content = json.dumps({"outcome": outcome, "evidence_event_ids": [], "root_cause": "unknown"})
        return LLMToolResponse(content if name is None else "", "test", "stop",
                               [] if name is None else [LLMToolCall(identifier, name, args)])

    async def run_agent(self, responses):
        self.provider = SimpleNamespace(generate_with_tools=AsyncMock(side_effect=responses))
        return await run_core_agent(self.provider, self.db, organization_id=self.org,
                                    case_id=self.case, as_of=self.now)

    async def test_actual_tool_domain_miss_is_final_only(self):
        from app.core.exceptions import NotFoundError
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                   new_callable=AsyncMock) as service:
            service.side_effect = NotFoundError("Missing case")
            result = await self.run_agent([
                self.response("get_exception_case", {"case_id": str(self.case)}), self.response(outcome="not_found"),
            ])
            self.assertEqual(result.trace[0]["result"]["status"], "not_found")
            self.assertEqual(self.provider.generate_with_tools.call_args.kwargs["tools"], [])
            service.assert_awaited_once_with(self.db, organization_id=self.org, case_id=self.case)

    async def test_execution_failure_is_not_sent_to_model(self):
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                   new_callable=AsyncMock) as service:
            service.side_effect = ConnectionError("offline")
            with self.assertRaises(CoreAgentError) as caught:
                await self.run_agent([self.response("get_exception_case", {"case_id": str(self.case)})])
            self.assertEqual(caught.exception.error_code, "tool_failed")
            self.assertEqual(caught.exception.trace[-1]["result"]["status"], "execution_failed")
            self.assertEqual(self.provider.generate_with_tools.await_count, 1)

    async def test_rejects_unobserved_final_wrong_first_case_and_unknown_tool(self):
        for response in (self.response(), self.response("write", {}),
                         self.response("get_exception_case", {"case_id": str(uuid4())}),
                         self.response("get_inventory_status", {"sku": "X"})):
            with self.subTest(response=response), self.assertRaises(CoreAgentError):
                await self.run_agent([response])
        self.db.execute.assert_not_called()

    async def test_context_injection_is_input_error_and_stops(self):
        result = await self.run_agent([
            self.response("get_exception_case", {"case_id": str(self.case), "organization_id": str(uuid4())}),
            self.response(outcome="invalid_input"),
        ])
        self.assertEqual(result.trace[0]["result"]["status"], "invalid_input")
        self.assertEqual(self.provider.generate_with_tools.call_args.kwargs["tools"], [])
        self.db.execute.assert_not_called()

    async def test_premature_answer_requires_analysis_and_returns_trace(self):
        case = SimpleNamespace(id=self.case, order_id=self.order, exception_type="other", status="open",
                               problem_description="Investigate", conclusion=None, evidence_event_ids=[],
                               opened_at=self.now, closed_at=None)
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                   new_callable=AsyncMock, return_value=case), patch(
            "app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
            new_callable=AsyncMock, return_value={"whole_order_completion": "unknown"},
        ) as analyze:
            result = await self.run_agent([
                self.response("get_exception_case", {"case_id": str(self.case)}),
                self.response(),
                self.response("analyze_fulfillment", {"order_id": str(self.order), "as_of": self.now.isoformat()}, "2"),
                self.response(),
            ])
            self.assertEqual(result.model_requests, 4)
            self.assertEqual([s["tool"] for s in result.trace], ["get_exception_case", "analyze_fulfillment"])
            self.assertEqual(self.provider.generate_with_tools.call_args.kwargs["tools"], [])
            analyze.assert_awaited_once_with(self.db, organization_id=self.org, order_id=self.order, as_of=self.now)

    async def test_repeated_premature_answers_exhaust_budget(self):
        case = SimpleNamespace(id=self.case, order_id=self.order, exception_type="other", status="open",
                               problem_description="Investigate", conclusion=None, evidence_event_ids=[],
                               opened_at=self.now, closed_at=None)
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                   new_callable=AsyncMock, return_value=case):
            with self.assertRaises(CoreAgentError):
                await self.run_agent([
                    self.response("get_exception_case", {"case_id": str(self.case)}),
                    *[self.response() for _ in range(8)],
                ])
            self.assertEqual(self.provider.generate_with_tools.await_count, 9)
