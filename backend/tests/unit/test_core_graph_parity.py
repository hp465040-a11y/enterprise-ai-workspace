"""Deterministic old-loop versus LangGraph replay; no model or database connection."""

import asyncio
import json
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents import core_agent as core
from app.ai.llm.base import LLMToolCall, LLMToolResponse

CASE = UUID("00000000-0000-0000-0000-000000000101")
ORDER = UUID("00000000-0000-0000-0000-000000000102")
ORG = UUID("00000000-0000-0000-0000-000000000103")
USER = UUID("00000000-0000-0000-0000-000000000104")
WORKSPACE = UUID("00000000-0000-0000-0000-000000000105")
EVENT = UUID("00000000-0000-0000-0000-000000000106")
CHUNK = UUID("00000000-0000-0000-0000-000000000107")
DOCUMENT = UUID("00000000-0000-0000-0000-000000000108")
NOW = datetime(2026, 10, 19, tzinfo=UTC)


def call(name, arguments, number):
    return LLMToolResponse("", "controlled", "tool_use", [LLMToolCall(str(number), name, arguments)])


def final(*, citations=(), knowledge=(), outcome="insufficient_evidence", root="unknown"):
    report = {"outcome": outcome, "evidence_event_ids": [str(item) for item in citations], "root_cause": root}
    if knowledge is not None:
        report["knowledge_source_ids"] = [str(item) for item in knowledge]
    return LLMToolResponse(json.dumps(report), "controlled", "stop")


class CoreGraphParityTests(unittest.IsolatedAsyncioTestCase):
    async def replay(self, implementation, responses, *, inventory=0, events=(),
                     event_error=None, knowledge=False, knowledge_status="found",
                     knowledge_denied=False, case_description=None):
        db = MagicMock(spec=AsyncSession)
        case = SimpleNamespace(
            id=CASE, order_id=ORDER, exception_type="other", status="open",
            problem_description=case_description or "Reservation/backorder review SKU=Sku-A;",
            conclusion=None, evidence_event_ids=[], opened_at=NOW, closed_at=None,
        )
        analysis = {"evidence_event_ids": [str(EVENT)] if events else [],
                    "shipment": {"status": "unknown", "reason": "completion_not_observed"},
                    "delivery": {"status": "unknown"}}
        snapshot = {"sku": "Sku-A", "available_quantity": inventory, "observed_at": NOW.isoformat()}
        observed_requests = []

        async def generate_with_tools(*, messages, tools, system):
            observed_requests.append({
                "tools": [tool.name for tool in tools], "system": system,
                "messages": [(message.role, message.content, message.tool_name,
                              [(tool.id, tool.name, tool.arguments) for tool in message.tool_calls])
                             for message in messages],
            })
            return responses[len(observed_requests) - 1]

        provider = SimpleNamespace(generate_with_tools=AsyncMock(side_effect=generate_with_tools))
        source = {"chunk_id": str(CHUNK), "document_id": str(DOCUMENT),
                  "document_filename": "SOP.pdf", "content": "Example SKU=FAKE is not order data.",
                  "page_number": 1, "relevance_score": 0.9}

        async def db_execute(statement):
            filters = {part.left.key: part.right.value for part in statement._where_criteria}
            if "workspace_id" in filters:
                member = None if knowledge_denied else SimpleNamespace(role="viewer")
            else:
                member = SimpleNamespace(role="member")
            return SimpleNamespace(scalar_one_or_none=lambda: member)

        db.execute.side_effect = db_execute
        db.get.return_value = SimpleNamespace(id=WORKSPACE, organization_id=ORG)
        with (patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                    new_callable=AsyncMock, return_value=case) as case_read,
              patch("app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
                    new_callable=AsyncMock, return_value=analysis) as analysis_read,
              patch("app.ai.tools.investigation_tools.inventory_service.get_inventory_status",
                    new_callable=AsyncMock, return_value=snapshot) as inventory_read,
              patch("app.ai.tools.investigation_tools.fulfillment_service.get_fulfillment_events",
                    new_callable=AsyncMock, return_value=list(events)) as event_read,
              patch("app.ai.tools.knowledge_tool.run_retrieval", new_callable=AsyncMock,
                    return_value=("SOP?", [source] if knowledge_status == "found" else [])) as retrieval):
            if event_error:
                event_read.side_effect = event_error
            try:
                result = await implementation(provider, db, organization_id=ORG, case_id=CASE,
                                              as_of=NOW, **({"user_id": USER, "workspace_id": WORKSPACE,
                                                            "require_knowledge": True} if knowledge else {}))
                outcome = {"status": "ok", "trace": result.trace, "report": result.report,
                           "answer": result.answer, "model_final": result.model_final,
                           "rejected": result.rejected_finals, "requests": result.model_requests}
            except core.CoreAgentError as exc:
                outcome = {"status": "error", "code": exc.error_code, "trace": exc.trace,
                           "rejected": exc.rejected_finals, "requests": exc.model_requests}
        return {"outcome": outcome, "provider_requests": observed_requests,
                "reads": [read.await_count for read in (
                    case_read, analysis_read, inventory_read, event_read, retrieval)]}

    async def compare(self, responses, **kwargs):
        old = await self.replay(core._run_core_agent_legacy, responses, **kwargs)
        graph = await self.replay(core.run_core_agent, responses, **kwargs)
        self.assertEqual(graph, old)
        return graph

    def opening(self):
        return [call("get_exception_case", {"case_id": str(CASE)}, 1),
                call("analyze_fulfillment", {"order_id": str(ORDER), "as_of": NOW.isoformat()}, 2)]

    def inventory(self):
        return call("get_inventory_status", {"sku": "Sku-A"}, 3)

    def event(self):
        return call("get_fulfillment_events", {"order_id": str(ORDER), "as_of": NOW.isoformat()}, 4)

    async def test_negative_inventory_stop_and_report_repair(self):
        result = await self.compare([*self.opening(), self.inventory(), final(outcome="observed_delay"),
                                     final(knowledge=None)], inventory=-3)
        self.assertEqual(result["outcome"]["status"], "ok")
        self.assertEqual(result["provider_requests"][-1]["tools"], [])
        self.assertEqual(result["reads"][3], 0)

    async def test_nonnegative_inventory_reads_events_and_repairs_missing_citation(self):
        event = SimpleNamespace(id=EVENT, event_type="in_transit", occurred_at=NOW,
                                expected_at=None, source="offline", external_event_id=None,
                                tracking_number="SHIP", description="Observed")
        result = await self.compare([*self.opening(), self.inventory(), self.event(),
                                     final(knowledge=None), final(citations=(EVENT,), knowledge=None)],
                                    inventory=2, events=(event,))
        self.assertEqual(result["outcome"]["report"]["evidence_event_ids"], [str(EVENT)])
        self.assertEqual(result["reads"][3], 1)

    async def test_required_knowledge_enters_final_only_and_cites_source(self):
        result = await self.compare([*self.opening(),
                                     call("search_knowledge", {"query": "SOP?"}, 3),
                                     final(knowledge=(CHUNK,))], knowledge=True,
                                    case_description="Which rule applies?")
        self.assertEqual(result["outcome"]["report"]["knowledge_source_ids"], [str(CHUNK)])
        self.assertEqual(result["provider_requests"][-1]["tools"], [])
        self.assertEqual(result["reads"][4], 1)

    async def test_no_matching_knowledge_keeps_business_outcome(self):
        result = await self.compare([*self.opening(),
                                     call("search_knowledge", {"query": "SOP?"}, 3),
                                     final(knowledge=())], knowledge=True, knowledge_status="no_matches",
                                    case_description="Which rule applies?")
        self.assertEqual(result["outcome"]["status"], "ok")
        self.assertEqual(result["outcome"]["trace"][-1]["result"]["status"], "no_matches")

    async def test_tool_fault_stops_without_report(self):
        result = await self.compare([*self.opening(), self.inventory(), self.event()],
                                    inventory=2, event_error=ConnectionError("offline"))
        self.assertEqual(result["outcome"]["code"], "tool_failed")
        self.assertEqual(result["reads"][3], 1)

    async def test_scope_violation_before_business_read(self):
        result = await self.compare([call("get_exception_case", {"case_id": str(ORDER)}, 1)])
        self.assertEqual(result["outcome"]["code"], "scope_violation")
        self.assertEqual(result["reads"][0], 0)

    async def test_knowledge_permission_denied_stops_without_report(self):
        result = await self.compare([*self.opening(), call("search_knowledge", {"query": "SOP?"}, 3)],
                                    knowledge=True, knowledge_denied=True,
                                    case_description="Which rule applies?")
        self.assertEqual(result["outcome"]["code"], "knowledge_permission_denied")
        self.assertEqual(result["reads"][4], 0)

    async def test_repeated_read_stops_before_second_query(self):
        result = await self.compare([*self.opening(),
                                     call("analyze_fulfillment", {"order_id": str(ORDER),
                                                                  "as_of": NOW.isoformat()}, 3)])
        self.assertEqual(result["outcome"]["code"], "repeated_call")
        self.assertEqual(result["reads"][1], 1)

    async def test_model_budget_exhaustion_matches(self):
        responses = [self.opening()[0], *[final(knowledge=None) for _ in range(8)]]
        result = await self.compare(responses)
        self.assertEqual(result["outcome"]["code"], "budget_exhausted")
        self.assertEqual(result["outcome"]["requests"], 9)
        self.assertEqual(result["reads"][1], 0)

    async def test_investigation_and_report_repair_budgets_remain_separate(self):
        result = await self.compare([*self.opening(),
                                     LLMToolResponse("I will read inventory next", "controlled", "stop"),
                                     self.inventory(), final(outcome="observed_delay", knowledge=None),
                                     final(knowledge=None)], inventory=-3)
        self.assertEqual(result["outcome"]["status"], "ok")
        self.assertEqual([item["phase"] for item in result["outcome"]["rejected"]],
                         ["investigation", "report"])

    async def test_tool_timeout_stops_without_another_model_request(self):
        async def stalled(*args, **kwargs):
            await asyncio.sleep(1)

        with patch.object(core, "TOOL_TIMEOUT_SECONDS", 0.2):
            result = await self.compare([*self.opening(), self.inventory(), self.event()],
                                        inventory=2, event_error=stalled)
        self.assertEqual(result["outcome"]["code"], "tool_timeout")
        self.assertEqual(result["outcome"]["requests"], 4)
