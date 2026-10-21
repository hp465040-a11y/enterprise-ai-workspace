"""Offline API -> real Core/Tool/report; controlled Provider and retrieval only."""

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents import core_agent as core
from app.ai.agents.investigation_report import evidence_contract, render_report, validate_report
from app.ai.llm.base import LLMToolCall, LLMToolResponse
from app.api.v1.router import api_router
from app.core.exceptions import register_exception_handlers
from app.core.security import create_access_token
from app.db.session import get_db
from app.middleware.request_context import RequestContextMiddleware


class CoreKnowledgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.org, self.user, self.workspace, self.case_id, self.order, self.event, self.chunk, self.doc = (
            uuid4() for _ in range(8))
        self.now = datetime(2026, 10, 16, tzinfo=UTC)
        self.db = MagicMock(spec=AsyncSession)
        self.workspace_role = "viewer"
        self.db.get.return_value = SimpleNamespace(id=self.workspace, organization_id=self.org)

        async def execute(statement):
            filters = {c.left.key: c.right.value for c in statement._where_criteria}
            self.assertEqual(filters["user_id"], self.user)
            if statement._raw_columns[0].name == "organization_members":
                self.assertEqual(filters["organization_id"], self.org)
                member = SimpleNamespace(user_id=self.user, organization_id=self.org, role="member")
            else:
                self.assertEqual(statement._raw_columns[0].name, "workspace_members")
                self.assertEqual(filters["workspace_id"], self.workspace)
                member = SimpleNamespace(user_id=self.user, workspace_id=self.workspace,
                                         role=self.workspace_role) if self.workspace_role else None
            return SimpleNamespace(scalar_one_or_none=lambda: member)

        self.db.execute.side_effect = execute
        self.case = SimpleNamespace(id=self.case_id, order_id=self.order, exception_type="other",
                                    status="open", problem_description="Which SOP applies to this review?",
                                    conclusion=None, evidence_event_ids=[], opened_at=self.now, closed_at=None)
        self.analysis = {"evidence_event_ids": [str(self.event)], "as_of": self.now.isoformat(),
                         "shipment": {"status": "unknown"}, "delivery": {"status": "unknown"}}
        self.case_service = self.enterContext(patch(
            "app.ai.tools.investigation_tools.exception_service.get_exception_case",
            new_callable=AsyncMock, return_value=self.case))
        self.analyze_service = self.enterContext(patch(
            "app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
            new_callable=AsyncMock, return_value=self.analysis))
        self.source = {"chunk_id": str(self.chunk), "document_id": str(self.doc),
                       "document_filename": "Review SOP.pdf", "content": "核对处理规则；不是订单事实。",
                       "page_number": 2, "relevance_score": 0.8}
        self.retrieve = self.enterContext(patch("app.ai.tools.knowledge_tool.run_retrieval",
                                               new_callable=AsyncMock, return_value=("SOP?", [self.source])))

    def call(self, name, arguments):
        return LLMToolResponse("", "controlled", "tool_use", [LLMToolCall(str(uuid4()), name, arguments)])

    def opening(self):
        return [self.call("get_exception_case", {"case_id": str(self.case_id)}),
                self.call("analyze_fulfillment", {"order_id": str(self.order), "as_of": self.now.isoformat()})]

    def final(self, ids=None, **changes):
        report = {"outcome": "insufficient_evidence", "root_cause": "unknown",
                  "evidence_event_ids": [str(self.event)], "knowledge_source_ids": ids or []}
        report.update(changes)
        return LLMToolResponse(json.dumps(report), "controlled", "stop")

    def sequence(self, ids=None, *, required=False):
        return [*self.opening(), self.call("search_knowledge", {"query": "SOP?"}),
                *([] if required else [self.call("finish_investigation", {})]),
                self.final([str(self.chunk)] if ids is None else ids)]

    async def run_sequence(self, responses, *, with_scope=True, require_knowledge=False):
        self.provider = SimpleNamespace(generate_with_tools=AsyncMock(side_effect=responses))
        context = {"user_id": self.user, "workspace_id": self.workspace} if with_scope else {}
        return await core.run_core_agent(self.provider, self.db, organization_id=self.org,
                                         case_id=self.case_id, as_of=self.now,
                                         require_knowledge=require_knowledge, **context)

    async def api_request(self, responses, *, require_knowledge=False):
        provider = SimpleNamespace(generate_with_tools=AsyncMock(side_effect=responses))
        app = FastAPI()
        register_exception_handlers(app)
        app.add_middleware(RequestContextMiddleware)
        app.include_router(api_router, prefix="/api/v1")

        async def offline_db():
            yield self.db

        app.dependency_overrides[get_db] = offline_db
        token = create_access_token(subject=str(self.user), organization_id=str(self.org))
        with (patch("app.api.v1.endpoints.investigations.get_llm_provider", return_value=provider),
              patch("app.services.auth_service.user_service.get_user_by_id", new_callable=AsyncMock,
                    return_value=SimpleNamespace(id=self.user, is_active=True))):
            async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                                   base_url="http://offline") as client:
                response = await client.post(f"/api/v1/organizations/{self.org}/investigations",
                    json={"case_id": str(self.case_id), "workspace_id": str(self.workspace),
                          "as_of": self.now.isoformat(), "require_knowledge": require_knowledge},
                    headers={"Authorization": f"Bearer {token}"})
        return response, provider

    async def test_api_real_core_tool_and_report_with_separate_citations(self):
        response, provider = await self.api_request(self.sequence())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["report"]["knowledge_source_ids"], [str(self.chunk)])
        self.assertEqual(body["report"]["evidence_event_ids"], [str(self.event)])
        self.assertEqual(body["report"]["root_cause"], "unknown")
        self.assertEqual(body["report"]["outcome"], "insufficient_evidence")
        self.assertEqual(body["request_id"], response.headers["X-Request-ID"])
        self.retrieve.assert_awaited_once_with(self.db, workspace_id=self.workspace, history=[], user_message="SOP?")
        self.case_service.assert_awaited_once_with(self.db, organization_id=self.org, case_id=self.case_id)
        self.assertEqual(self.db.execute.await_count, 4)  # API and Tool both check org + workspace.
        choices = provider.generate_with_tools.call_args_list[2].kwargs["tools"]
        knowledge = next(t for t in choices if t.name == "search_knowledge")
        self.assertEqual(set(knowledge.input_schema["properties"]), {"query"})
        self.assertFalse(knowledge.input_schema["additionalProperties"])
        self.assertIn("知识参考（非业务事实）", body["handoff"])
        self.assertIn(self.source["document_filename"], body["handoff"])
        self.assertIn("未验证片段是否支持建议", body["handoff"])
        facts = body["handoff"].split("2. 证据引用及观察时间")[0]
        self.assertNotIn(self.source["content"], facts)
        self.assertNotIn("trace", body)
        self.db.commit.assert_not_awaited()

    async def test_no_workspace_keeps_old_report_and_no_knowledge_tool(self):
        result = await self.run_sequence([*self.opening(), self.call("finish_investigation", {}),
                                          self.final()], with_scope=False)
        for request in self.provider.generate_with_tools.call_args_list:
            self.assertNotIn("search_knowledge", [t.name for t in request.kwargs["tools"]])
        self.assertEqual(set(result.report), {"outcome", "root_cause", "evidence_event_ids"})
        self.retrieve.assert_not_awaited()

    async def test_required_lookup_blocks_all_three_completion_forms(self):
        endings = [self.call("finish_investigation", {}),
                   LLMToolResponse("FINISH", "controlled", "stop"), self.final()]
        for ending in endings:
            with self.subTest(ending=ending), self.assertRaises(core.CoreAgentError) as caught:
                await self.run_sequence([*self.opening(), ending], require_knowledge=True)
            self.assertEqual(caught.exception.error_code, "missing_knowledge")
            choices = self.provider.generate_with_tools.call_args_list[-1].kwargs["tools"]
            self.assertNotIn("finish_investigation", [t.name for t in choices])
            self.assertIn("search_knowledge", [t.name for t in choices])
        self.retrieve.assert_not_awaited()

    def saved_c05_decisions(self):
        path = Path(__file__).resolve().parents[3] / "scripts/investigation_api_c05_20261016T152854003114Z.json"
        evidence = json.loads(path.read_text(encoding="utf-8"))
        # Replay the actual fake-text and native-finish responses; opening observations use this fixture.
        responses = []
        for request in evidence["requests"][2:4]:
            response = request["response"]
            responses.append(LLMToolResponse(
                response["content"], response["model"], response["stop_reason"],
                [LLMToolCall(c["id"], c["name"], c["arguments"]) for c in response["tool_calls"]],
            ))
        return responses

    async def test_saved_c05_skip_is_rejected_before_report(self):
        with self.assertRaises(core.CoreAgentError) as caught:
            await self.run_sequence([*self.opening(), *self.saved_c05_decisions()], require_knowledge=True)
        self.assertEqual(caught.exception.error_code, "missing_knowledge")
        self.assertEqual(caught.exception.model_requests, 4)
        self.assertEqual(caught.exception.rejected_finals[0]["phase"], "investigation")
        self.retrieve.assert_not_awaited()

    def saved_post_lookup_failure(self, filename="investigation_api_c05_20261017T142615923918Z.json"):
        path = Path(__file__).resolve().parents[3] / "scripts" / filename
        evidence = json.loads(path.read_text(encoding="utf-8"))
        case = evidence["trace"][0]["result"]["case"]
        self.case_id, self.order = UUID(case["id"]), UUID(case["order_id"])
        self.case.id, self.case.order_id = self.case_id, self.order
        self.case.problem_description = case["problem_description"]
        self.analysis = evidence["trace"][1]["result"]["analysis"]
        self.analyze_service.return_value = self.analysis
        self.now = datetime.fromisoformat(self.analysis["as_of"])
        self.source = evidence["trace"][2]["result"]["sources"][0]
        self.chunk = UUID(self.source["chunk_id"])
        self.retrieve.return_value = ("SOP?", [self.source])
        responses = []
        for request in evidence["requests"]:
            if "response" not in request:
                continue
            response = request["response"]
            responses.append(LLMToolResponse(
                response["content"], response["model"], response["stop_reason"],
                [LLMToolCall(c["id"], c["name"], c["arguments"]) for c in response["tool_calls"]],
            ))
        return responses

    async def test_saved_missing_events_feedback_and_model_repair(self):
        responses = self.saved_post_lookup_failure("investigation_api_c05_20261017T144515065498Z.json")
        bad = responses[-1].content
        expected_ids = set(self.analysis["evidence_event_ids"])
        submitted_ids = set(json.loads(bad)["evidence_event_ids"])
        with self.assertRaises(ValueError):
            validate_report(bad, [
                {"tool": "analyze_fulfillment", "result": {"status": "found", "analysis": self.analysis}},
                {"tool": "search_knowledge", "result": {"status": "found", "sources": [self.source]}},
            ])
        corrected = self.final([str(self.chunk)], outcome="observed_delay",
                               evidence_event_ids=sorted(expected_ids))
        result = await self.run_sequence([*responses, corrected], require_knowledge=True)
        self.assertEqual(result.model_requests, 6)
        self.assertEqual([r["phase"] for r in result.rejected_finals], ["investigation", "report"])
        self.assertEqual(result.rejected_finals[-1]["content"], bad)
        self.assertEqual(result.model_final, corrected.content)
        requests = self.provider.generate_with_tools.call_args_list
        first = requests[4].kwargs
        self.assertEqual(first["tools"], [])
        self.assertIn("Include ALL observed event IDs", first["system"])
        if [m.role for m in first["messages"]] == ["user"]:
            self.assertIn("keep retrieved chunk IDs", first["system"])
            compact = json.loads(first["messages"][0].content.split("\n", 1)[1])
            observations = [step["result"] for step in compact["verified_tool_observations"]]
            self.assertEqual(set(compact["required_report_citations"]["evidence_event_ids"]), expected_ids)
            self.assertEqual(compact["required_report_citations"]["knowledge_source_ids"], [str(self.chunk)])
        else:
            # This saved C05 sequence had an investigation rejection, so the clean-path
            # compactor deliberately preserves its original complete message history.
            observations = [json.loads(m.content) for m in first["messages"] if m.role == "tool"]
        self.assertTrue(any(set(o.get("analysis", {}).get("evidence_event_ids", [])) == expected_ids
                            for o in observations))
        self.assertTrue(any(o.get("sources") == [self.source] for o in observations))
        feedback = requests[5].kwargs["messages"][-1].content
        marker = "Citation differences in your candidate: "
        differences, _ = json.JSONDecoder().raw_decode(feedback.split(marker, 1)[1])
        missing = differences["missing_evidence_event_ids"]
        self.assertEqual(missing, sorted(expected_ids - submitted_ids))
        self.assertEqual(len(missing), 3)
        self.assertNotIn(str(self.chunk), missing)
        self.assertEqual(differences["missing_knowledge_source_ids"], [])
        self.assertIn("Business event IDs belong in evidence_event_ids", feedback)
        self.assertEqual(set(result.report["evidence_event_ids"]), expected_ids)
        self.assertEqual(result.report["knowledge_source_ids"], [str(self.chunk)])
        self.assertEqual(result.report["outcome"], "observed_delay")
        self.assertEqual(result.report["root_cause"], "unknown")

    async def test_saved_missing_events_twice_still_fails(self):
        responses = self.saved_post_lookup_failure("investigation_api_c05_20261017T144515065498Z.json")
        with self.assertRaises(core.CoreAgentError) as caught:
            await self.run_sequence([*responses, responses[-1]], require_knowledge=True)
        self.assertEqual(caught.exception.error_code, "ungrounded_final")
        self.assertEqual(caught.exception.model_requests, 6)
        self.assertEqual([r["phase"] for r in caught.exception.rejected_finals],
                         ["investigation", "report", "report"])

    def test_missing_event_feedback_does_not_invent_omissions(self):
        trace = [{"tool": "analyze_fulfillment", "result": {"status": "found", "analysis": self.analysis}}]
        for content in ("not JSON", '{"name":"get_inventory_status"}', self.final().content):
            with self.subTest(content=content):
                self.assertEqual(core._missing_event_citation_feedback(content, trace), "")
        no_events = [{"tool": "analyze_fulfillment", "result": {
            "status": "found", "analysis": {"evidence_event_ids": []}}}]
        self.assertEqual(core._missing_event_citation_feedback(
            self.final(evidence_event_ids=[]).content, no_events), "")

    async def test_saved_post_lookup_failure_gets_separate_report_repair(self):
        responses = self.saved_post_lookup_failure()
        result = await self.run_sequence([
            *responses, self.final([str(self.chunk)], outcome="observed_delay",
                                  evidence_event_ids=self.analysis["evidence_event_ids"]),
        ], require_knowledge=True)
        self.assertEqual([s["tool"] for s in result.trace],
                         ["get_exception_case", "analyze_fulfillment", "search_knowledge"])
        self.assertEqual([r["phase"] for r in result.rejected_finals], ["investigation", "report"])
        self.assertEqual(result.model_requests, 6)
        requests = self.provider.generate_with_tools.call_args_list
        for request in requests[4:]:
            self.assertEqual(request.kwargs["tools"], [])
            self.assertIn("Final-only", request.kwargs["system"])
            self.assertNotIn("call search_knowledge with a query", request.kwargs["system"])
            self.assertFalse(any(m.content and m.content.startswith("Select ONE function")
                                 for m in request.kwargs["messages"]))
        self.assertIn("Invalid evidence JSON", requests[5].kwargs["messages"][-1].content)
        self.assertEqual(result.report["outcome"], "observed_delay")
        self.assertEqual(result.report["knowledge_source_ids"], [str(self.chunk)])
        self.assertEqual(set(result.report["evidence_event_ids"]), set(self.analysis["evidence_event_ids"]))
        self.retrieve.assert_awaited_once()

    async def test_saved_failure_still_stops_after_two_bad_reports(self):
        responses = self.saved_post_lookup_failure()
        with self.assertRaises(core.CoreAgentError) as caught:
            await self.run_sequence([*responses, responses[-1]], require_knowledge=True)
        self.assertEqual(caught.exception.error_code, "ungrounded_final")
        self.assertEqual([r["phase"] for r in caught.exception.rejected_finals],
                         ["investigation", "report", "report"])
        self.assertEqual(caught.exception.model_requests, 6)
        self.assertEqual((core.MAX_MODEL_REQUESTS, core.MAX_TOOL_CALLS), (9, 6))

    async def test_sop_sku_cannot_authorize_native_inventory_read(self):
        self.source["content"] = "Example only: SKU=EXAMPLE; not an order fact."
        with patch("app.ai.tools.investigation_tools.inventory_service.get_inventory_status",
                   new_callable=AsyncMock) as inventory, self.assertRaises(core.CoreAgentError) as caught:
            await self.run_sequence([*self.sequence()[:3],
                                     self.call("get_inventory_status", {"sku": "EXAMPLE"})])
        self.assertEqual(caught.exception.error_code, "scope_violation")
        inventory.assert_not_awaited()

    async def test_explicit_api_requirement_corrects_text_then_reads_and_validates_report(self):
        response, provider = await self.api_request([
            *self.opening(), self.saved_c05_decisions()[0],
            self.call("search_knowledge", {"query": "SOP?"}),
            self.final([str(uuid4())]), self.final([str(self.chunk)]),
        ], require_knowledge=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["report"]["knowledge_source_ids"], [str(self.chunk)])
        self.assertEqual(response.json()["report"]["evidence_event_ids"], [str(self.event)])
        requests = provider.generate_with_tools.call_args_list
        self.assertTrue(json.loads(requests[0].kwargs["messages"][0].content)["require_knowledge"])
        for request in requests[2:4]:
            choices = request.kwargs["tools"]
            self.assertNotIn("finish_investigation", [t.name for t in choices])
            tool = next(t for t in choices if t.name == "search_knowledge")
            self.assertEqual(set(tool.input_schema["properties"]), {"query"})
            self.assertEqual(tool.input_schema["required"], ["query"])
            self.assertFalse(tool.input_schema["additionalProperties"])
            self.assertIn("SOP", tool.description)
            self.assertTrue("explicitly requires" in request.kwargs["system"] or
                            any("required native SOP read" in message.content
                                for message in request.kwargs["messages"]))
        feedback = requests[3].kwargs["messages"][-1].content
        self.assertIn("required next read is search_knowledge", feedback)
        self.assertNotIn("finish_investigation", feedback)
        self.assertNotIn("get_fulfillment_events", feedback)
        self.assertEqual(requests[-1].kwargs["tools"], [])
        self.assertIn("Invalid evidence JSON", requests[-1].kwargs["messages"][-1].content)
        self.assertEqual(len(requests), 6)
        self.assertEqual((core.MAX_MODEL_REQUESTS, core.MAX_TOOL_CALLS), (9, 6))

    async def test_scope_and_sop_record_alone_do_not_require_lookup(self):
        result = await self.run_sequence([*self.opening(), self.call("finish_investigation", {}), self.final()])
        self.assertEqual(result.report["root_cause"], "unknown")
        self.assertNotIn("require_knowledge", json.loads(
            self.provider.generate_with_tools.call_args_list[0].kwargs["messages"][0].content))
        self.retrieve.assert_not_awaited()

    async def test_required_no_matches_completes_lookup_without_invented_citations(self):
        self.retrieve.return_value = ("SOP?", [])
        responses = self.sequence(ids=[], required=True)
        responses[-1] = self.final([str(self.chunk)])
        result = await self.run_sequence([*responses, self.final()], require_knowledge=True)
        self.assertEqual(result.trace[-1]["result"]["status"], "no_matches")
        self.assertNotIn("knowledge_source_ids", result.report)
        self.assertEqual(len(result.rejected_finals), 1)
        self.assertEqual(self.provider.generate_with_tools.call_args_list[-1].kwargs["tools"], [])

    async def test_required_lookup_permission_and_failure_are_not_success(self):
        for denied in (True, False):
            with self.subTest(denied=denied):
                self.workspace_role = None if denied else "viewer"
                self.retrieve.side_effect = None if denied else ConnectionError("PRIVATE_BACKEND")
                with self.assertRaises(core.CoreAgentError) as caught:
                    await self.run_sequence(self.sequence(), require_knowledge=True)
                self.assertEqual(caught.exception.error_code, "knowledge_permission_denied" if denied else "tool_failed")
                self.assertEqual(self.provider.generate_with_tools.await_count, 3)
                if denied:
                    self.retrieve.assert_not_awaited()

    async def test_required_lookup_survives_business_automatic_stop(self):
        self.case.problem_description = "reservation/backorder review SKU=Sku-A;"
        for quantity in (-3, 7):
            with self.subTest(quantity=quantity), patch(
                "app.ai.tools.investigation_tools.inventory_service.get_inventory_status",
                new_callable=AsyncMock, return_value={"available_quantity": quantity,
                    "sku": "Sku-A", "observed_at": self.now.isoformat()},
            ), patch("app.ai.tools.investigation_tools.fulfillment_service.get_fulfillment_events",
                     new_callable=AsyncMock, return_value=[]):
                calls = [*self.opening(), self.call("get_inventory_status", {"sku": "Sku-A"})]
                if quantity >= 0:
                    calls.append(self.call("get_fulfillment_events",
                        {"order_id": str(self.order), "as_of": self.now.isoformat()}))
                result = await self.run_sequence([*calls, *self.sequence(required=True)[2:]], require_knowledge=True)
                self.assertEqual(result.trace[-1]["tool"], "search_knowledge")
                requests = self.provider.generate_with_tools.call_args_list
                self.assertNotIn("search_knowledge", [t.name for t in requests[2].kwargs["tools"]])
                self.assertIn("search_knowledge", [t.name for t in requests[len(calls)].kwargs["tools"]])
                self.assertEqual(requests[-1].kwargs["tools"], [])

    async def test_required_lookup_with_no_events_and_missing_case(self):
        self.analysis["evidence_event_ids"] = []
        responses = self.sequence(required=True)
        responses[-1] = self.final(["K1"], evidence_event_ids=[])
        result = await self.run_sequence(responses, require_knowledge=True)
        self.assertEqual(result.report["outcome"], "insufficient_evidence")
        from app.core.exceptions import NotFoundError

        self.case_service.side_effect = NotFoundError("missing case")
        self.retrieve.reset_mock()
        result = await self.run_sequence([self.opening()[0], self.final(
            outcome="not_found", evidence_event_ids=[])], require_knowledge=True)
        self.assertEqual(result.report["outcome"], "not_found")
        self.retrieve.assert_not_awaited()
        self.assertEqual(self.provider.generate_with_tools.call_args_list[-1].kwargs["tools"], [])

    async def test_required_lookup_never_extends_tool_budget(self):
        with patch.object(core, "MAX_TOOL_CALLS", 2), self.assertRaises(core.CoreAgentError) as caught:
            await self.run_sequence(self.sequence(), require_knowledge=True)
        self.assertEqual(caught.exception.error_code, "budget_exhausted")
        self.assertEqual(self.provider.generate_with_tools.await_count, 2)
        self.retrieve.assert_not_awaited()

    async def test_forged_knowledge_citation_is_rejected_then_corrected(self):
        responses = self.sequence()
        responses[-1] = self.final([str(uuid4())])
        result = await self.run_sequence([*responses, self.final([str(self.chunk)])])
        self.assertEqual(len(result.rejected_finals), 1)
        self.assertEqual(result.rejected_finals[0]["phase"], "report")
        self.assertEqual(result.report["knowledge_source_ids"], [str(self.chunk)])
        for request in self.provider.generate_with_tools.call_args_list[-2:]:
            self.assertEqual(request.kwargs["tools"], [])

    async def test_repeated_bad_citations_fail_without_more_budget(self):
        responses = self.sequence()
        responses[-1] = self.final([str(uuid4())])
        with self.assertRaises(core.CoreAgentError) as caught:
            await self.run_sequence([*responses, self.final([str(uuid4())])])
        self.assertEqual(caught.exception.error_code, "ungrounded_final")
        self.assertEqual(self.provider.generate_with_tools.await_count, 6)
        self.assertEqual((core.MAX_MODEL_REQUESTS, core.MAX_TOOL_CALLS), (9, 6))

    async def test_no_matches_preserves_business_outcome_and_has_no_citations(self):
        self.retrieve.return_value = ("SOP?", [])
        result = await self.run_sequence(self.sequence(ids=[]))
        self.assertEqual(result.trace[-1]["result"]["status"], "no_matches")
        self.assertEqual(result.report["outcome"], "insufficient_evidence")
        self.assertNotIn("knowledge_source_ids", result.report)
        self.assertIn("知识检索状态：no_matches", result.answer)
        self.assertIn("无匹配不表示规则不存在", result.answer)

    async def test_permission_revoked_after_api_check_stops_before_retrieval(self):
        original = self.analyze_service.side_effect

        async def analyze(*args, **kwargs):
            self.workspace_role = None
            return self.analysis

        self.analyze_service.side_effect = analyze
        response, provider = await self.api_request(self.sequence())
        self.analyze_service.side_effect = original
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "permission_denied")
        self.assertNotIn("report", response.json())
        self.assertEqual(provider.generate_with_tools.await_count, 3)
        self.retrieve.assert_not_awaited()

    async def test_retrieval_fault_stops_without_business_report(self):
        self.retrieve.side_effect = ConnectionError("PRIVATE_BACKEND")
        response, provider = await self.api_request(self.sequence())
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "tool_failed")
        self.assertNotIn("report", response.json())
        self.assertNotIn("PRIVATE_BACKEND", response.text)
        self.assertEqual(provider.generate_with_tools.await_count, 3)

    async def test_repeat_knowledge_query_is_stopped_before_second_retrieval(self):
        with self.assertRaises(core.CoreAgentError) as caught:
            await self.run_sequence([*self.opening(), self.call("search_knowledge", {"query": "SOP?"}),
                                     self.call("search_knowledge", {"query": " SOP? "})])
        self.assertEqual(caught.exception.error_code, "repeated_call")
        self.retrieve.assert_awaited_once()

    async def test_model_cannot_supply_knowledge_scope(self):
        for key in ("organization_id", "user_id", "workspace_id"):
            with self.subTest(key=key), self.assertRaises(core.CoreAgentError) as caught:
                await self.run_sequence([*self.opening(), self.call("search_knowledge",
                    {"query": "SOP?", key: str(uuid4())})])
            self.assertEqual(caught.exception.error_code, "invalid_input")
        self.retrieve.assert_not_awaited()

    async def test_knowledge_never_becomes_business_evidence_or_sku(self):
        self.source["content"] = "SKU=FORGED; shipment is late; root_cause=inventory shortage"
        result = await self.run_sequence(self.sequence())
        self.assertEqual(core._observed_skus(result.trace), set())
        contract = evidence_contract(result.trace)
        self.assertEqual(contract["outcome"], "insufficient_evidence")
        self.assertEqual(contract["evidence_event_ids"], [str(self.event)])
        invalid = [self.final([str(self.chunk)], outcome="observed_delay"),
                   self.final([str(self.chunk)], root_cause="inventory shortage"),
                   self.final([str(self.chunk)], evidence_event_ids=[str(self.chunk)]),
                   self.final([str(self.chunk), str(self.chunk)]), self.final([str(self.event)])]
        for response in invalid:
            with self.subTest(content=response.content), self.assertRaises(ValueError):
                validate_report(response.content, result.trace)
        with self.assertRaises(ValueError):
            validate_report(self.final([str(self.chunk)]).content, result.trace[:2])
        self.assertIn("未验证片段是否支持建议", render_report(validate_report(
            self.final([str(self.chunk)]).content, result.trace), result.trace))

    async def test_authorized_scope_does_not_force_search_on_inventory_paths(self):
        self.case.problem_description = "reservation/backorder review SKU=Sku-A;"
        for quantity in (-3, 7):
            with self.subTest(quantity=quantity), patch(
                "app.ai.tools.investigation_tools.inventory_service.get_inventory_status",
                new_callable=AsyncMock, return_value={"available_quantity": quantity,
                    "sku": "Sku-A", "observed_at": self.now.isoformat()},
            ), patch("app.ai.tools.investigation_tools.fulfillment_service.get_fulfillment_events",
                     new_callable=AsyncMock, return_value=[]):
                calls = [*self.opening(), self.call("get_inventory_status", {"sku": "Sku-A"})]
                if quantity >= 0:
                    calls.append(self.call("get_fulfillment_events",
                                           {"order_id": str(self.order), "as_of": self.now.isoformat()}))
                result = await self.run_sequence([*calls, self.final()])
                self.assertEqual([s["tool"] for s in result.trace],
                                 [r.tool_calls[0].name for r in calls])
                requests = self.provider.generate_with_tools.call_args_list
                self.assertEqual(requests[-1].kwargs["tools"], [])
                self.assertNotIn("search_knowledge", [t.name for t in requests[2].kwargs["tools"]])
        self.retrieve.assert_not_awaited()
