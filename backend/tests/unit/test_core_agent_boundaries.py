"""Stop/error and historical bad-case regression without global fixtures."""
import asyncio
import json
import re
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.core_agent import CoreAgentError, run_core_agent
from app.ai.agents.investigation_report import evidence_contract, render_report, validate_report
from app.ai.llm.base import LLMToolCall, LLMToolResponse


class ReportTests(unittest.TestCase):
    def test_saved_c04_wrong_outcome_and_text_tool_intent_are_not_reports(self):
        root = Path(__file__).resolve().parents[3]
        saved = json.loads((root / "scripts/day13_evidence_20261011T124733894433Z.json").read_text(encoding="utf-8"))
        case = next(c for c in saved["cases"] if c["scenario"] == "C04")
        self.assertEqual(case["error_code"], "ungrounded_final")
        self.assertEqual(evidence_contract(case["trace"])["outcome"], "insufficient_evidence")
        for rejected in case["rejected_finals"]:
            with self.assertRaises((ValueError, ValidationError)):
                validate_report(rejected["content"], case["trace"])

    def test_real_d11_trace_renders_deadline_difference_and_ids(self):
        root = Path(__file__).resolve().parents[3]
        saved = json.loads((root / "scripts/day11_evidence_20261011T100235914092Z.json").read_text(encoding="utf-8"))
        contract = evidence_contract(saved["trace"])
        report = validate_report(json.dumps(contract), saved["trace"])
        answer = render_report(report, saved["trace"])
        self.assertEqual(contract["outcome"], "observed_delay")
        self.assertIn("2026-10-09T10:00:00+00:00", answer)
        self.assertIn('"difference_seconds": 3600.0', answer)
        for identifier in contract["evidence_event_ids"]:
            self.assertIn(identifier, answer)

    def test_historical_bad_finals_cannot_pass_new_contract(self):
        root = Path(__file__).resolve().parents[3]
        for name in ("day11_evidence.json", "day11_evidence_20261011T093249272924Z.json",
                     "day11_evidence_20261011T100235914092Z.json"):
            saved = json.loads((root / "scripts" / name).read_text(encoding="utf-8"))
            with self.subTest(name=name), self.assertRaises((ValueError, ValidationError)):
                validate_report(saved["answer"], saved["trace"])

    def test_missing_fabricated_duplicate_citations_and_root_cause_rejected(self):
        identifier = str(uuid4())
        trace = [{"tool": "analyze_fulfillment", "result": {"status": "found", "analysis": {
            "evidence_event_ids": [identifier], "shipment": {"status": "late"},
        }}}]
        correct = evidence_contract(trace)
        for change in ({"evidence_event_ids": []}, {"evidence_event_ids": [str(uuid4())]},
                       {"evidence_event_ids": [identifier, identifier]}, {"root_cause": "inventory shortage"},
                       {"outcome": "no_observed_delay"}, {"summary": "invented cause"}):
            with self.subTest(change=change), self.assertRaises((ValueError, ValidationError)):
                validate_report(json.dumps(correct | change), trace)
        report = validate_report(json.dumps(correct), trace)
        rendered = render_report(report, trace)
        self.assertIn(identifier, rendered)
        self.assertIn("Root cause: unknown", rendered)

    def saved_handoff(self, filename, scenario):
        root = Path(__file__).resolve().parents[3]
        saved = json.loads((root / "scripts" / filename).read_text(encoding="utf-8"))
        case = next(c for c in saved["cases"] if c["scenario"] == scenario)
        trace = case["trace"]
        original = json.dumps(trace, sort_keys=True)
        report = validate_report(json.dumps(case["report"]), trace)
        answer = render_report(report, trace)
        self.assertEqual(json.dumps(trace, sort_keys=True), original)
        self.assertEqual(report.model_dump(mode="json"), case["report"])
        titles = ["1. 已确认事实", "2. 证据引用及观察时间", "3. 不能确认的事项",
                  "4. 缺少的资料", "5. 与资料缺口逐项对应的下一步建议", "6. 处理状态"]
        self.assertEqual([section.splitlines()[0] for section in answer.split("\n\n")], titles)
        missing = re.findall(r"^- G(\d+)：", answer, re.MULTILINE)
        suggestions = re.findall(r"^- G(\d+)（建议，尚未执行）：", answer, re.MULTILINE)
        self.assertEqual(missing, suggestions)
        self.assertIn("本次未通知、未分派、未执行处置；不会自动继续调查", answer)
        return trace, answer

    def test_handoff_complete_timing_keeps_scope_citations_and_distinct_times(self):
        trace, answer = self.saved_handoff("day13_evidence_20261015T051730341912Z.json", "C01")
        analysis = trace[1]["result"]["analysis"]
        self.assertIn("Outcome: no_observed_delay", answer)
        self.assertIn("不证明整单履约正常或完成", answer)
        self.assertIn("分析时点 as_of（观察截止，非事件发生时间）：" + analysis["as_of"], answer)
        for kind, label in (("shipment", "发货"), ("delivery", "送达")):
            comparison = analysis[kind]
            self.assertIn(f"{label}业务时间：承诺截止 {comparison['expected_at']}；实际完成 {comparison['actual_at']}", answer)
            self.assertIn('"difference_seconds": ' + str(comparison["difference_seconds"]), answer)
            self.assertIn("比较范围：shipment", answer)
        for identifier in analysis["evidence_event_ids"]:
            self.assertIn(identifier, answer)
        self.assertNotIn("建议，尚未执行", answer)
        self.assertIn("案件记录状态：open（仅转述读取值，本次未变更）", answer)

    def test_handoff_no_events_pairs_missing_times_with_conservative_suggestions(self):
        _, answer = self.saved_handoff("day13_evidence_20261014T145330173273Z.json", "C06")
        self.assertIn("Outcome: insufficient_evidence", answer)
        self.assertIn("无已观察事件引用", answer)
        self.assertIn("不能据此断言实际没有发货或送达", answer)
        for label in ("发货", "送达"):
            for name in ("承诺截止时间", "实际完成时间"):
                self.assertIn(f"{label}：可比较的{name}未提供", answer)
                self.assertIn(f"{label}{name}记录及来源", answer)
        self.assertEqual(answer.count("（建议，尚未执行）"), 4)
        self.assertNotIn("该时间比较未观察到延迟", answer)

    def test_handoff_negative_inventory_is_snapshot_not_order_shortage(self):
        trace, answer = self.saved_handoff("day13_evidence_20261013T155810143158Z.json", "C03")
        inventory = trace[2]["result"]["inventory"]
        self.assertIn("可用数量=-3", answer)
        self.assertIn("SKU=" + inventory["sku"], answer)
        self.assertIn("库存观察时间 observed_at（非事件时间或分析时点）：" + inventory["observed_at"], answer)
        self.assertIn("不能证明本订单缺货、预留情况或异常根因", answer)
        self.assertIn("Root cause: unknown", answer)
        self.assertIn("Outcome: insufficient_evidence", answer)

    def test_handoff_missing_case_is_not_normality_or_a_closed_case(self):
        _, answer = self.saved_handoff("day13_evidence_20261014T144608932959Z.json", "C07")
        self.assertIn("Outcome: not_found", answer)
        self.assertIn("不是履约正常的证明", answer)
        self.assertIn("核对本次查询标识与授权范围内的对应记录", answer)
        self.assertIn("案件记录状态：未提供", answer)
        self.assertIn("无已观察事件引用", answer)
        self.assertNotIn("已读取案件：", answer)
        self.assertIn("事件发生时间、库存观察时间和分析时点：未提供", answer)
        self.assertNotIn("2026-", answer)

    def test_handoff_missing_metadata_and_event_claims_are_not_invented(self):
        identifier = "00000000-0000-0000-0000-000000000001"
        trace = [
            {"tool": "get_inventory_status", "result": {"status": "found", "inventory": {
                "available_quantity": -1}}},
            {"tool": "get_fulfillment_events", "result": {"status": "found", "events": [
                {"event_id": identifier, "description": "Source alleges warehouse shortage"}]}},
        ]
        report = validate_report(json.dumps(evidence_contract(trace)), trace)
        answer = render_report(report, trace)
        self.assertIn("SKU=未提供", answer)
        self.assertIn("库存观察时间 observed_at（非事件时间或分析时点）：未提供", answer)
        self.assertIn("发生时间 occurred_at=未提供", answer)
        self.assertIn("来源描述（未核实的来源陈述，不是因果结论）：Source alleges warehouse shortage", answer)
        self.assertNotIn("Source alleges", answer.split("2. 证据引用及观察时间")[0])
        self.assertNotIn("2026-", answer)
        self.assertEqual(answer.count("（建议，尚未执行）"), 3)
        trace[0]["result"]["inventory"]["observed_at"] = "2026-10-09T10:00:00+00:00"
        trace[1]["result"]["events"][0]["occurred_at"] = "2026-10-09T11:00:00+00:00"
        trace.append({"tool": "analyze_fulfillment", "result": {"status": "found", "analysis": {
            "as_of": "2026-10-09T12:00:00+00:00", "evidence_event_ids": [identifier]}}})
        report = validate_report(json.dumps(evidence_contract(trace)), trace)
        answer = render_report(report, trace)
        self.assertIn("库存观察时间 observed_at（非事件时间或分析时点）：2026-10-09T10:00:00+00:00", answer)
        self.assertIn("发生时间 occurred_at=2026-10-09T11:00:00+00:00", answer)
        self.assertIn("分析时点 as_of（观察截止，非事件发生时间）：2026-10-09T12:00:00+00:00", answer)
        self.assertEqual(render_report(report, trace), answer)


class BoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_schema_repair_does_not_execute_bad_arguments(self):
        self.case.problem_description = "Review SKU=Sku-A;"
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                   new_callable=AsyncMock, return_value=self.case), patch(
            "app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
            new_callable=AsyncMock, return_value={"evidence_event_ids": []},
        ) as service:
            final = LLMToolResponse(json.dumps({"outcome": "insufficient_evidence",
                                               "evidence_event_ids": [], "root_cause": "unknown"}), "stub", "stop")
            result = await self.run_responses([
                self.case_call(), self.call("analyze_fulfillment", {"case": "wrong wrapper"}, "bad"),
                self.analysis_call(), final,
            ])
            self.assertEqual(service.await_count, 1)
            self.assertEqual(result.trace[1]["result"]["status"], "invalid_input")
            self.assertTrue(result.trace[1]["result"]["retryable"])
            self.assertEqual(result.trace[2]["result"]["status"], "found")

    async def test_schema_repair_is_bounded_to_one_then_final_only(self):
        final = LLMToolResponse(json.dumps({"outcome": "invalid_input", "evidence_event_ids": [],
                                           "root_cause": "unknown"}), "stub", "stop")
        result = await self.run_responses([
            self.call("get_exception_case", {"case": "wrong"}, "one"),
            self.call("get_exception_case", {"case": "still wrong"}, "two"), final,
        ])
        self.assertFalse(result.trace[-1]["result"]["retryable"])
        self.assertEqual(self.provider.generate_with_tools.call_args.kwargs["tools"], [])
        self.db.execute.assert_not_called()

    def setUp(self):
        self.case_id, self.order_id, self.org = uuid4(), uuid4(), uuid4()
        self.now = datetime(2026, 10, 11, tzinfo=UTC)
        self.case = SimpleNamespace(id=self.case_id, order_id=self.order_id, exception_type="other",
                                    status="open", problem_description="Reservation pending; SKU=Sku-A;",
                                    conclusion=None, evidence_event_ids=[], opened_at=self.now, closed_at=None)
        self.db = MagicMock(spec=AsyncSession)

    def call(self, name, args, identifier):
        return LLMToolResponse("", "stub", "tool_use", [LLMToolCall(identifier, name, args)])

    async def run_responses(self, responses):
        self.provider = SimpleNamespace(generate_with_tools=AsyncMock(side_effect=responses))
        return await run_core_agent(self.provider, self.db, organization_id=self.org,
                                    case_id=self.case_id, as_of=self.now)

    def case_call(self, identifier="a"):
        return self.call("get_exception_case", {"case_id": str(self.case_id)}, identifier)

    async def test_finish_separates_model_decision_from_report_without_more_reads(self):
        self.case.problem_description = "Review SKU=Sku-A;"
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                   new_callable=AsyncMock, return_value=self.case), patch(
            "app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
            new_callable=AsyncMock, return_value={"evidence_event_ids": []},
        ) as service:
            final = json.dumps({"outcome": "insufficient_evidence", "evidence_event_ids": [], "root_cause": "unknown"})
            result = await self.run_responses([
                self.case_call(), self.analysis_call(),
                self.call("finish_investigation", {}, "finish"), LLMToolResponse(final, "stub", "stop"),
            ])
            requests = self.provider.generate_with_tools.call_args_list
            for decision in requests[1:3]:
                self.assertEqual(decision.kwargs["messages"][-1].role, "user")
                self.assertEqual(decision.kwargs["messages"][-2].role, "tool")
            self.assertIn("required analyze_fulfillment", requests[1].kwargs["messages"][-1].content)
            self.assertIn(str(self.order_id), requests[1].kwargs["messages"][-1].content)
            self.assertIn("Cumulative verified facts:", requests[2].kwargs["messages"][-1].content)
            self.assertEqual({t.name for t in requests[2].kwargs["tools"]}, {
                "get_exception_case", "analyze_fulfillment", "get_inventory_status",
                "finish_investigation",
            })
            self.assertEqual(requests[3].kwargs["tools"], [])
            self.assertEqual(result.model_requests, 4)
            self.assertEqual(len(result.trace), 2)
            self.assertEqual(result.rejected_finals, [])
            service.assert_awaited_once()

    async def test_finish_control_cannot_skip_evidence_or_supply_business_arguments(self):
        for arguments, expected in (({}, "missing_analysis"), ({"order_id": str(self.order_id)}, "protocol_error")):
            with self.subTest(arguments=arguments), self.assertRaises(CoreAgentError) as caught:
                await self.run_responses([self.call("finish_investigation", arguments, "finish")])
            self.assertEqual(caught.exception.error_code, expected)
            self.assertEqual(caught.exception.trace, [])
        self.db.execute.assert_not_called()

    async def test_inventory_offering_after_analysis_requires_observed_sku(self):
        identifier = str(uuid4())
        all_tools = {"get_exception_case", "analyze_fulfillment", "get_inventory_status",
                     "get_fulfillment_events", "finish_investigation"}
        for source in ("none", "tracking_number", "case", "promise_note"):
            with self.subTest(source=source):
                self.case.problem_description = "Review SKU=Sku-A;" if source == "case" else "Review timing."
                analysis = {"evidence_event_ids": [identifier], "whole_order_completion": "unknown",
                            "shipment": {"status": "on_time"}, "delivery": {"status": "on_time"}}
                if source == "tracking_number":
                    analysis["shipment"]["tracking_number"] = "TRACK-ONLY"
                if source == "promise_note":
                    analysis["timeline"] = [{"event_type": "shipment_promised", "event_id": identifier,
                                             "description": "Review SKU=Sku-A;"}]
                final = LLMToolResponse(json.dumps({"outcome": "no_observed_delay",
                    "evidence_event_ids": [identifier], "root_cause": "unknown"}), "stub", "stop")
                with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                           new_callable=AsyncMock, return_value=self.case), patch(
                    "app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
                    new_callable=AsyncMock, return_value=analysis,
                ):
                    result = await self.run_responses([
                        self.case_call(), self.analysis_call(),
                        self.call("finish_investigation", {}, "finish"), final,
                    ])
                requests = self.provider.generate_with_tools.call_args_list
                for request in requests[:2]:
                    self.assertEqual({t.name for t in request.kwargs["tools"]}, all_tools)
                expected = all_tools - {"get_fulfillment_events"}
                if source in ("none", "tracking_number"):
                    expected -= {"get_inventory_status"}
                self.assertEqual({t.name for t in requests[2].kwargs["tools"]}, expected)
                self.assertNotIn("Final-only: no tools", requests[2].kwargs["system"])
                self.assertEqual(requests[3].kwargs["tools"], [])
                self.assertEqual([s["tool"] for s in result.trace], ["get_exception_case", "analyze_fulfillment"])
                self.assertEqual(result.report["evidence_event_ids"], [identifier])
                self.db.execute.assert_not_called()

    async def test_hidden_inventory_call_still_rejected_before_tool_execution(self):
        from app.ai.tools.investigation_tools import create_investigation_tools

        self.case.problem_description = "Review timing."
        tools = create_investigation_tools(self.db, organization_id=self.org)
        inventory_tool = next(t for t in tools if t.name == "get_inventory_status")
        with patch("app.ai.agents.core_agent.create_investigation_tools", return_value=tools), patch(
            "app.ai.tools.investigation_tools.exception_service.get_exception_case",
            new_callable=AsyncMock, return_value=self.case,
        ), patch("app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
                 new_callable=AsyncMock, return_value={"evidence_event_ids": [str(uuid4())],
                     "shipment": {"status": "on_time", "tracking_number": "TRACK-ONLY"},
                     "delivery": {"status": "on_time"}}), patch(
            "app.ai.tools.investigation_tools.inventory_service.get_inventory_status", new_callable=AsyncMock,
        ) as inventory, patch.object(type(inventory_tool), "ainvoke", autospec=True,
                                     side_effect=type(inventory_tool).ainvoke) as invoke:
            with self.assertRaises(CoreAgentError) as caught:
                await self.run_responses([
                    self.case_call(), self.analysis_call(),
                    self.call("get_inventory_status", {"sku": "TRACK-ONLY"}, "inventory"),
                ])
            self.assertEqual(caught.exception.error_code, "scope_violation")
            self.assertEqual([s["tool"] for s in caught.exception.trace],
                             ["get_exception_case", "analyze_fulfillment"])
            self.assertNotIn("get_inventory_status", {
                t.name for t in self.provider.generate_with_tools.call_args.kwargs["tools"]})
            self.assertEqual([call.args[0].name for call in invoke.await_args_list],
                             ["get_exception_case", "analyze_fulfillment"])
            inventory.assert_not_awaited()
            self.db.execute.assert_not_called()

    async def test_saved_c03_event_before_inventory_is_rejected(self):
        from app.ai.tools.investigation_tools import create_investigation_tools

        def load_evidence():
            root = Path(__file__).resolve().parents[3]
            return json.loads((root / "scripts/day13_evidence_20261013T075745093286Z.json").read_text(encoding="utf-8"))

        saved = await asyncio.to_thread(load_evidence)
        case = saved["cases"][0]
        observations = {step["tool"]: step["result"] for step in case["trace"]}
        tools = [SimpleNamespace(name=t.name, description=t.description, get_input_schema=t.get_input_schema,
                                 ainvoke=AsyncMock(return_value=observations[t.name]))
                 for t in create_investigation_tools(self.db, organization_id=self.org)]
        responses = [self.call(r["response"]["tool_calls"][0]["name"],
                               r["response"]["tool_calls"][0]["arguments"], str(r["request"]))
                     for r in case["requests"]]
        provider = SimpleNamespace(generate_with_tools=AsyncMock(side_effect=responses))
        with patch("app.ai.agents.core_agent.create_investigation_tools", return_value=tools), \
                self.assertRaises(CoreAgentError) as caught:
            await run_core_agent(provider, self.db, organization_id=self.org,
                                 case_id=UUID(case["case_id"]),
                                 as_of=datetime.fromisoformat(case["trace"][1]["arguments"]["as_of"]))
        self.assertEqual(caught.exception.error_code, "missing_inventory")
        self.assertEqual(provider.generate_with_tools.await_count, 3)
        self.assertEqual(len(caught.exception.trace), 2)
        for tool in tools:
            if tool.name in ("get_fulfillment_events", "get_inventory_status"):
                tool.ainvoke.assert_not_awaited()
        self.db.execute.assert_not_called()

    async def inventory_path(self, snapshot, tail, *, event_result=None):
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                   new_callable=AsyncMock, return_value=self.case), patch(
            "app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
            new_callable=AsyncMock, return_value={"shipment": {"status": "unknown",
                "reason": "completion_not_observed", "deadline_exceeded": True}},
        ), patch("app.ai.tools.investigation_tools.inventory_service.get_inventory_status",
                 new_callable=AsyncMock) as inventory, patch(
            "app.ai.tools.investigation_tools.fulfillment_service.get_fulfillment_events",
            new_callable=AsyncMock, return_value=[],
        ) as events:
            if isinstance(event_result, Exception):
                events.side_effect = event_result
            elif event_result is not None:
                events.return_value = event_result
            inventory.side_effect = snapshot if isinstance(snapshot, Exception) else None
            inventory.return_value = snapshot
            try:
                return await self.run_responses([
                    self.case_call(), self.analysis_call(),
                    self.call("get_inventory_status", {"sku": "Sku-A"}, "inventory"), *tail,
                ])
            finally:
                inventory.assert_awaited_once_with(self.db, organization_id=self.org, sku="Sku-A")
                self.events_count = events.await_count
                self.db.execute.assert_not_called()

    def report_response(self, outcome="insufficient_evidence", root_cause="unknown"):
        return LLMToolResponse(json.dumps({"outcome": outcome, "evidence_event_ids": [],
                                          "root_cause": root_cause}), "stub", "stop")

    async def test_negative_dated_inventory_enters_report_with_contract_validation(self):
        for bad in (self.report_response("observed_delay"),
                    self.report_response(root_cause="inventory shortage")):
            with self.subTest(bad=bad):
                result = await self.inventory_path(
                    {"available_quantity": -3, "observed_at": self.now.isoformat()},
                    [bad, self.report_response()],
                )
                self.assertEqual(result.report["outcome"], "insufficient_evidence")
                self.assertEqual(result.report["root_cause"], "unknown")
                self.assertEqual(len(result.rejected_finals), 1)
                self.assertEqual(len(result.trace), 3)
                self.assertEqual(self.events_count, 0)
                for request in self.provider.generate_with_tools.call_args_list[3:]:
                    self.assertEqual(request.kwargs["tools"], [])
                    self.assertFalse(any(m.content.startswith("Select ONE function")
                                         for m in request.kwargs["messages"]))
                self.assertIn(self.now.isoformat(), result.answer)

    async def test_negative_inventory_rejects_further_read_in_final_only(self):
        with self.assertRaises(CoreAgentError) as caught:
            await self.inventory_path(
                {"available_quantity": -3, "observed_at": self.now.isoformat()},
                [self.call("get_fulfillment_events", {"order_id": str(self.order_id),
                                                     "as_of": self.now.isoformat()}, "events")],
            )
        self.assertEqual(caught.exception.error_code, "protocol_error")
        self.assertEqual(self.events_count, 0)
        self.assertEqual(self.provider.generate_with_tools.call_args.kwargs["tools"], [])

    async def test_nonnegative_or_undated_inventory_keeps_event_path(self):
        snapshots = [{"available_quantity": q, "observed_at": self.now.isoformat()} for q in (0, 7)]
        snapshots.append({"available_quantity": -3})
        snapshots.extend({"available_quantity": -3, "observed_at": date}
                         for date in (None, "invalid", "2026-10-11T00:00:00"))
        for snapshot in snapshots:
            with self.subTest(snapshot=snapshot):
                finish = [] if snapshot["available_quantity"] >= 0 else [
                    self.call("finish_investigation", {}, "finish")]
                result = await self.inventory_path(snapshot, [
                    self.call("get_fulfillment_events", {"order_id": str(self.order_id),
                                                        "as_of": self.now.isoformat()}, "events"),
                    *finish, self.report_response(),
                ])
                self.assertEqual(self.events_count, 1)
                self.assertTrue(self.provider.generate_with_tools.call_args_list[3].kwargs["tools"])
                self.assertEqual(result.report["outcome"], "insufficient_evidence")

    async def test_event_tool_offered_only_after_inventory_success(self):
        for quantity in (0, 7):
            with self.subTest(quantity=quantity):
                await self.inventory_path(
                    {"available_quantity": quantity, "observed_at": self.now.isoformat()},
                    [self.call("get_fulfillment_events", {"order_id": str(self.order_id),
                                                        "as_of": self.now.isoformat()}, "events"),
                     self.report_response()],
                )
                requests = self.provider.generate_with_tools.call_args_list
                all_tools = {"get_exception_case", "analyze_fulfillment", "get_inventory_status",
                             "get_fulfillment_events", "finish_investigation"}
                for request in requests[:2]:
                    self.assertEqual({tool.name for tool in request.kwargs["tools"]}, all_tools)
                self.assertEqual({tool.name for tool in requests[2].kwargs["tools"]},
                                 all_tools - {"get_fulfillment_events", "finish_investigation"})
                self.assertEqual({tool.name for tool in requests[3].kwargs["tools"]},
                                 all_tools - {"finish_investigation"})
                self.assertEqual(requests[4].kwargs["tools"], [])
                self.assertIn("Final-only: no tools", requests[4].kwargs["system"])

    def ending_responses(self):
        return [self.call("finish_investigation", {}, "finish"),
                LLMToolResponse("FINISH", "stub", "stop"), self.report_response()]

    async def test_successful_events_enter_report_and_preserve_citation_validation(self):
        identifier = uuid4()
        event = SimpleNamespace(id=identifier, event_type="in_transit", occurred_at=self.now,
                                expected_at=None, source="offline", external_event_id=None,
                                tracking_number="SHIP-A", description="Original warehouse note")
        correct = LLMToolResponse(json.dumps({"outcome": "insufficient_evidence",
            "evidence_event_ids": [str(identifier)], "root_cause": "unknown"}), "stub", "stop")
        result = await self.inventory_path(
            {"available_quantity": 7, "observed_at": self.now.isoformat()}, [
                self.call("get_fulfillment_events", {"order_id": str(self.order_id),
                                                    "as_of": self.now.isoformat()}, "events"),
                self.report_response(), correct,
            ], event_result=[event],
        )
        self.assertEqual(result.report["evidence_event_ids"], [str(identifier)])
        self.assertEqual(len(result.rejected_finals), 1)
        observed = result.trace[-1]["result"]
        self.assertEqual(observed["events"][0]["description"], event.description)
        for request in self.provider.generate_with_tools.call_args_list[4:]:
            self.assertEqual(request.kwargs["tools"], [])
            self.assertIn("Final-only: no tools", request.kwargs["system"])
            event_message = next(m for m in request.kwargs["messages"] if m.tool_name == "get_fulfillment_events")
            self.assertEqual(json.loads(event_message.content), observed)
        self.assertIn(str(identifier), result.answer)

    async def test_event_failure_stops_without_report_request(self):
        with self.assertRaises(CoreAgentError) as caught:
            await self.inventory_path(
                {"available_quantity": 7, "observed_at": self.now.isoformat()}, [
                    self.call("get_fulfillment_events", {"order_id": str(self.order_id),
                                                        "as_of": self.now.isoformat()}, "events"),
                ], event_result=ConnectionError("offline"),
            )
        self.assertEqual(caught.exception.error_code, "tool_failed")
        self.assertEqual(caught.exception.trace[-1]["result"]["status"], "execution_failed")
        self.assertEqual(self.provider.generate_with_tools.await_count, 4)

    async def test_missing_events_keep_terminal_not_found_semantics(self):
        from app.core.exceptions import NotFoundError
        result = await self.inventory_path(
            {"available_quantity": 7, "observed_at": self.now.isoformat()}, [
                self.call("get_fulfillment_events", {"order_id": str(self.order_id),
                                                    "as_of": self.now.isoformat()}, "events"),
                self.report_response("not_found"),
            ], event_result=NotFoundError("Missing events"),
        )
        self.assertEqual(result.trace[-1]["result"]["status"], "not_found")
        self.assertEqual(result.report["outcome"], "not_found")

    async def test_invalid_event_arguments_keep_input_repair_before_report(self):
        result = await self.inventory_path(
            {"available_quantity": 7, "observed_at": self.now.isoformat()}, [
                self.call("get_fulfillment_events", {"parameters": {}}, "bad"),
                self.call("get_fulfillment_events", {"order_id": str(self.order_id),
                                                    "as_of": self.now.isoformat()}, "events"),
                self.report_response(),
            ],
        )
        self.assertEqual(result.trace[-2]["result"]["status"], "invalid_input")
        requests = self.provider.generate_with_tools.call_args_list
        self.assertTrue(requests[4].kwargs["tools"])
        self.assertNotIn("Final-only: no tools", requests[4].kwargs["system"])
        self.assertEqual(requests[5].kwargs["tools"], [])
        self.assertEqual(self.events_count, 1)

    async def test_events_without_reservation_clue_keep_investigation_decision(self):
        self.case.problem_description = "Review SKU=Sku-A;"
        await self.inventory_path({"available_quantity": 7, "observed_at": self.now.isoformat()}, [
            self.call("get_fulfillment_events", {"order_id": str(self.order_id),
                                                "as_of": self.now.isoformat()}, "events"),
            self.call("finish_investigation", {}, "finish"), self.report_response(),
        ])
        requests = self.provider.generate_with_tools.call_args_list
        self.assertTrue(requests[4].kwargs["tools"])
        self.assertEqual(requests[5].kwargs["tools"], [])

    async def test_reservation_cannot_finish_before_inventory(self):
        for ending in self.ending_responses():
            with self.subTest(ending=ending), patch(
                "app.ai.tools.investigation_tools.exception_service.get_exception_case",
                new_callable=AsyncMock, return_value=self.case,
            ), patch("app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
                     new_callable=AsyncMock, return_value={"evidence_event_ids": []}), \
                    self.assertRaises(CoreAgentError) as caught:
                await self.run_responses([self.case_call(), self.analysis_call(), ending])
            self.assertEqual(caught.exception.error_code, "missing_inventory")
            self.assertEqual(len(caught.exception.trace), 2)
            self.assertEqual(self.provider.generate_with_tools.await_count, 3)
            offered = {t.name for t in self.provider.generate_with_tools.call_args.kwargs["tools"]}
            self.assertNotIn("finish_investigation", offered)
            self.assertIn("get_inventory_status", offered)
        self.db.execute.assert_not_called()

    async def test_nonnegative_inventory_cannot_finish_before_events(self):
        for quantity in (0, 7):
            for ending in self.ending_responses():
                with self.subTest(quantity=quantity, ending=ending), self.assertRaises(CoreAgentError) as caught:
                    await self.inventory_path(
                        {"available_quantity": quantity, "observed_at": self.now.isoformat()}, [ending],
                    )
                self.assertEqual(caught.exception.error_code, "missing_events")
                self.assertEqual(self.events_count, 0)
                self.assertEqual(self.provider.generate_with_tools.await_count, 4)
                offered = {t.name for t in self.provider.generate_with_tools.call_args.kwargs["tools"]}
                self.assertNotIn("finish_investigation", offered)
                self.assertIn("get_fulfillment_events", offered)

    async def test_backorder_sku_in_analysis_also_blocks_finish(self):
        self.case.problem_description = "Investigate timing"
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                   new_callable=AsyncMock, return_value=self.case), patch(
            "app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
            new_callable=AsyncMock, return_value={"timeline": [{
                "event_type": "shipment_promised", "event_id": str(uuid4()),
                "description": "Backorder review for SKU=Sku-A;",
            }]},
        ), self.assertRaises(CoreAgentError) as caught:
            await self.run_responses([self.case_call(), self.analysis_call(),
                                      self.call("finish_investigation", {}, "finish")])
        self.assertEqual(caught.exception.error_code, "missing_inventory")
        self.db.execute.assert_not_called()

    async def test_reservation_without_explicit_sku_keeps_existing_stop(self):
        self.case.problem_description = "Reservation review pending"
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                   new_callable=AsyncMock, return_value=self.case), patch(
            "app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
            new_callable=AsyncMock, return_value={"evidence_event_ids": []},
        ):
            result = await self.run_responses([self.case_call(), self.analysis_call(), self.report_response()])
        self.assertEqual(result.report["outcome"], "insufficient_evidence")
        self.assertEqual(self.provider.generate_with_tools.call_args.kwargs["tools"], [])
        self.db.execute.assert_not_called()

    async def test_undated_nonnegative_inventory_does_not_add_finish_gate(self):
        result = await self.inventory_path({"available_quantity": 7}, [
            self.call("finish_investigation", {}, "finish"), self.report_response(),
        ])
        self.assertEqual(result.report["outcome"], "insufficient_evidence")
        self.assertIn("finish_investigation", {
            t.name for t in self.provider.generate_with_tools.call_args_list[3].kwargs["tools"]})

    async def test_missing_inventory_retains_not_found_report(self):
        from app.core.exceptions import NotFoundError
        result = await self.inventory_path(NotFoundError("Missing inventory"),
                                           [self.report_response("not_found")])
        self.assertEqual(result.report["outcome"], "not_found")
        self.assertEqual(result.trace[-1]["result"]["status"], "not_found")
        self.assertEqual(self.provider.generate_with_tools.call_args.kwargs["tools"], [])
        self.assertEqual(self.events_count, 0)

    async def test_inventory_failure_retains_error_without_report(self):
        with self.assertRaises(CoreAgentError) as caught:
            await self.inventory_path(ConnectionError("offline"), [])
        self.assertEqual(caught.exception.error_code, "tool_failed")
        self.assertEqual(caught.exception.trace[-1]["result"]["status"], "execution_failed")
        self.assertEqual(self.provider.generate_with_tools.await_count, 3)
        self.assertEqual(self.events_count, 0)

    async def test_final_only_invalid_report_feedback_states_verified_outcome_reason(self):
        self.case.problem_description = "Review SKU=Sku-A;"
        def report(outcome):
            return json.dumps({"outcome": outcome, "evidence_event_ids": [], "root_cause": "unknown"})
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                   new_callable=AsyncMock, return_value=self.case), patch(
            "app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
            new_callable=AsyncMock, return_value={
                "evidence_event_ids": [],
                "shipment": {"status": "unknown", "reason": "completion_not_observed", "actual_at": None},
                "delivery": {"status": "unknown", "reason": "missing_promise", "actual_at": None},
            },
        ):
            result = await self.run_responses([
                self.case_call(), self.analysis_call(), self.call("finish_investigation", {}, "finish"),
                LLMToolResponse(report("observed_delay"), "stub", "stop"),
                LLMToolResponse(report("insufficient_evidence"), "stub", "stop"),
            ])
        self.assertEqual(result.report["outcome"], "insufficient_evidence")
        self.assertEqual(len(result.rejected_finals), 1)
        self.assertEqual(result.rejected_finals[0]["reason"], "invalid_evidence_report")
        feedback = self.provider.generate_with_tools.call_args_list[4].kwargs["messages"][-1].content
        self.assertIn('"outcome": "insufficient_evidence"', feedback)
        self.assertIn("Expected outcome=insufficient_evidence", feedback)
        self.assertIn("no comparable actual shipment completion time was observed", feedback)
        self.assertIn("Return only corrected evidence JSON", feedback)
        self.assertEqual(self.provider.generate_with_tools.call_args_list[3].kwargs["tools"], [])

    async def test_text_tool_intent_is_not_executed_and_native_retry_keeps_tools(self):
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                   new_callable=AsyncMock, return_value=self.case), patch(
            "app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
            new_callable=AsyncMock, return_value={"evidence_event_ids": []},
        ), patch("app.ai.tools.investigation_tools.inventory_service.get_inventory_status",
                 new_callable=AsyncMock, return_value={"available_quantity": -3}) as inventory:
            final = json.dumps({"outcome": "insufficient_evidence", "evidence_event_ids": [], "root_cause": "unknown"})
            result = await self.run_responses([
                self.case_call(), self.analysis_call(),
                LLMToolResponse('{"name":"get_inventory_status","parameters":{"sku":"Sku-A"}}', "stub", "stop"),
                self.call("get_inventory_status", {"sku": "Sku-A"}, "c"),
                LLMToolResponse("FINISH", "stub", "stop"), LLMToolResponse(final, "stub", "stop"),
            ])
            self.assertEqual(len(self.provider.generate_with_tools.call_args_list[3].kwargs["tools"]), 3)
            correction = self.provider.generate_with_tools.call_args_list[3].kwargs
            feedback = correction["messages"][-1].content
            self.assertIn("required next read is get_inventory_status", feedback)
            self.assertNotIn("finish_investigation", feedback)
            self.assertNotIn("get_fulfillment_events", feedback)
            self.assertEqual({t.name for t in correction["tools"]}, {
                "get_exception_case", "analyze_fulfillment", "get_inventory_status",
            })
            inventory.assert_awaited_once()
            self.assertEqual(len(result.trace), 3)
            self.assertEqual(len(result.rejected_finals), 1)

    def analysis_call(self, identifier="b", **changes):
        return self.call("analyze_fulfillment", {"order_id": str(self.order_id),
                                                "as_of": self.now.isoformat(), **changes}, identifier)

    async def test_invalid_text_after_nonnegative_inventory_feedback_matches_tools(self):
        for quantity in (0, 7):
            with self.subTest(quantity=quantity):
                result = await self.inventory_path(
                    {"available_quantity": quantity, "observed_at": self.now.isoformat()}, [
                        LLMToolResponse("I will read the events next.", "stub", "stop"),
                        self.call("get_fulfillment_events", {"order_id": str(self.order_id),
                                                            "as_of": self.now.isoformat()}, "events"),
                        self.report_response(),
                    ],
                )
                correction = self.provider.generate_with_tools.call_args_list[4].kwargs
                feedback = correction["messages"][-1].content
                self.assertIn("required next read is get_fulfillment_events", feedback)
                self.assertNotIn("finish_investigation", feedback)
                self.assertNotIn("get_inventory_status", feedback)
                self.assertEqual({t.name for t in correction["tools"]}, {
                    "get_exception_case", "analyze_fulfillment", "get_inventory_status",
                    "get_fulfillment_events",
                })
                self.assertEqual(self.events_count, 1)
                self.assertEqual(result.report["outcome"], "insufficient_evidence")

    async def test_invalid_text_without_pending_read_keeps_original_feedback(self):
        self.case.problem_description = "Review SKU=Sku-A;"
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                   new_callable=AsyncMock, return_value=self.case), patch(
            "app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
            new_callable=AsyncMock, return_value={"evidence_event_ids": []},
        ):
            await self.run_responses([
                self.case_call(), self.analysis_call(), LLMToolResponse("I will finish.", "stub", "stop"),
                self.call("finish_investigation", {}, "finish"), self.report_response(),
            ])
        correction = self.provider.generate_with_tools.call_args_list[3].kwargs
        self.assertEqual(correction["messages"][-1].content, (
            "Invalid investigation response. A tool mentioned in ordinary text was NOT executed. "
            "Choose a native tool call with its exact schema if another read is needed. "
            "Output the tool call alone, without any preceding or following prose. "
            "Otherwise call finish_investigation with no arguments. Do not narrate a future tool call."
        ))
        self.assertIn("finish_investigation", {t.name for t in correction["tools"]})
        self.db.execute.assert_not_called()

    async def test_investigation_rejection_preserves_report_repair_budget(self):
        invalid_text = LLMToolResponse(
            '{"name":"get_inventory_status","parameters":{"sku":"Sku-A"}}', "stub", "stop",
        )
        wrong = self.report_response("observed_delay")
        for second_wrong in (False, True):
            with self.subTest(second_wrong=second_wrong), patch(
                "app.ai.tools.investigation_tools.exception_service.get_exception_case",
                new_callable=AsyncMock, return_value=self.case,
            ), patch("app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
                     new_callable=AsyncMock, return_value={"evidence_event_ids": []}), patch(
                "app.ai.tools.investigation_tools.inventory_service.get_inventory_status",
                new_callable=AsyncMock,
                return_value={"available_quantity": 7, "observed_at": self.now.isoformat()},
            ) as inventory, patch(
                "app.ai.tools.investigation_tools.fulfillment_service.get_fulfillment_events",
                new_callable=AsyncMock, return_value=[],
            ) as events:
                responses = [
                    self.case_call(), self.analysis_call(), invalid_text,
                    self.call("get_inventory_status", {"sku": "Sku-A"}, "inventory"),
                    self.call("get_fulfillment_events", {"order_id": str(self.order_id),
                                                        "as_of": self.now.isoformat()}, "events"),
                    wrong, wrong if second_wrong else self.report_response(),
                ]
                if second_wrong:
                    with self.assertRaises(CoreAgentError) as caught:
                        await self.run_responses(responses)
                    self.assertEqual(caught.exception.error_code, "ungrounded_final")
                    rejected = caught.exception.rejected_finals
                    self.assertEqual([r["phase"] for r in rejected], ["investigation", "report", "report"])
                else:
                    result = await self.run_responses(responses)
                    rejected = result.rejected_finals
                    self.assertEqual([r["phase"] for r in rejected], ["investigation", "report"])
                    self.assertEqual(result.report["outcome"], "insufficient_evidence")
                    self.assertEqual(result.report["root_cause"], "unknown")
                    self.assertEqual([s["tool"] for s in result.trace], [
                        "get_exception_case", "analyze_fulfillment", "get_inventory_status",
                        "get_fulfillment_events",
                    ])
                self.assertEqual(rejected[0]["content"], invalid_text.content)
                self.assertEqual(rejected[1]["content"], wrong.content)
                requests = self.provider.generate_with_tools.call_args_list
                self.assertEqual(len(requests), 7)
                self.assertEqual(requests[5].kwargs["tools"], [])
                self.assertEqual(requests[6].kwargs["tools"], [])
                self.assertIn("Return only corrected evidence JSON", requests[6].kwargs["messages"][-1].content)
                inventory.assert_awaited_once()
                events.assert_awaited_once()
                self.db.execute.assert_not_called()

    async def test_repeated_call_different_ids_executes_service_once(self):
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                   new_callable=AsyncMock, return_value=self.case) as service:
            with self.assertRaises(CoreAgentError) as caught:
                await self.run_responses([self.case_call(), self.case_call("different")])
            self.assertEqual(caught.exception.error_code, "repeated_call")
            self.assertEqual(service.await_count, 1)

    async def test_timezone_normalization_prevents_repeat_bypass(self):
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                   new_callable=AsyncMock, return_value=self.case), patch(
            "app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
            new_callable=AsyncMock, return_value={"evidence_event_ids": []},
        ) as service:
            with self.assertRaises(CoreAgentError) as caught:
                await self.run_responses([self.case_call(), self.analysis_call(),
                                         self.analysis_call("c", as_of="2026-10-11T08:00:00+08:00")])
            self.assertEqual(caught.exception.error_code, "repeated_call")
            self.assertEqual(service.await_count, 1)

    async def test_cross_order_cutoff_and_fabricated_sku_rejected(self):
        variants = [self.analysis_call(order_id=str(uuid4())),
                    self.analysis_call(as_of="2026-10-10T00:00:00Z"),
                    self.call("get_inventory_status", {"sku": "invented"}, "c")]
        for request in variants:
            with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                       new_callable=AsyncMock, return_value=self.case):
                with self.assertRaises(CoreAgentError) as caught:
                    await self.run_responses([self.case_call(), request])
                self.assertEqual(caught.exception.error_code, "scope_violation")

    async def test_actual_async_timeout_stops_no_second_model_call(self):
        async def stalled(*args, **kwargs):
            await asyncio.sleep(1)
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case", side_effect=stalled), patch(
            "app.ai.agents.core_agent.TOOL_TIMEOUT_SECONDS", 0.01,
        ):
            with self.assertRaises(CoreAgentError) as caught:
                await self.run_responses([self.case_call()])
            self.assertEqual(caught.exception.error_code, "tool_timeout")
            self.assertEqual(self.provider.generate_with_tools.await_count, 1)
            self.assertEqual(caught.exception.trace[-1]["result"]["status"], "execution_failed")

    async def test_model_budget_exhausted_and_no_extra_query(self):
        with patch("app.ai.agents.core_agent.MAX_MODEL_REQUESTS", 1):
            with self.assertRaises(CoreAgentError) as caught:
                await self.run_responses([self.case_call()])
            self.assertEqual(caught.exception.error_code, "budget_exhausted")
            self.db.execute.assert_not_called()

    async def test_model_failure_is_not_business_observation(self):
        with self.assertRaises(CoreAgentError) as caught:
            await self.run_responses([ConnectionError("secret connection string")])
        self.assertEqual(caught.exception.error_code, "model_failed")
        self.assertEqual(caught.exception.trace, [])
        self.assertNotIn("secret", str(caught.exception))

    async def test_invalid_final_repair_has_strict_limit(self):
        from app.core.exceptions import NotFoundError
        wrong = LLMToolResponse("Order is normal, no problem", "stub", "stop")
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                   new_callable=AsyncMock, side_effect=NotFoundError("Missing")):
            with self.assertRaises(CoreAgentError) as caught:
                await self.run_responses([self.case_call(), wrong, wrong])
            self.assertEqual(caught.exception.error_code, "ungrounded_final")
            self.assertEqual(len(caught.exception.rejected_finals), 2)
            self.assertEqual(self.provider.generate_with_tools.call_args.kwargs["tools"], [])

    async def test_tool_budget_rejects_extra_call_without_executing_it(self):
        with patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                   new_callable=AsyncMock, return_value=self.case), patch(
            "app.ai.agents.core_agent.MAX_TOOL_CALLS", 1,
        ):
            with self.assertRaises(CoreAgentError) as caught:
                await self.run_responses([self.case_call(), self.analysis_call()])
            self.assertEqual(caught.exception.error_code, "budget_exhausted")
            self.assertEqual(len(caught.exception.trace), 1)
            self.assertEqual(self.provider.generate_with_tools.call_args.kwargs["tools"], [])

    async def test_multi_call_batch_executes_nothing(self):
        response = self.case_call()
        response.tool_calls.append(self.analysis_call().tool_calls[0])
        with self.assertRaises(CoreAgentError) as caught:
            await self.run_responses([response])
        self.assertEqual(caught.exception.error_code, "protocol_error")
        self.db.execute.assert_not_called()

    async def test_model_timeout_has_distinct_error(self):
        async def stalled(**kwargs):
            await asyncio.sleep(1)
        provider = SimpleNamespace(generate_with_tools=stalled)
        with patch("app.ai.agents.core_agent.MODEL_TIMEOUT_SECONDS", 0.01), self.assertRaises(CoreAgentError) as caught:
            await run_core_agent(provider, self.db, organization_id=self.org,
                                 case_id=self.case_id, as_of=self.now)
        self.assertEqual(caught.exception.error_code, "model_timeout")
        self.assertEqual(caught.exception.trace, [])
