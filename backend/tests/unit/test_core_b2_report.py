"""Self-contained B2-shaped report replay; no raw evidence, database, or model."""

import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from app.ai.agents import core_agent as core
from app.ai.agents import core_graph
from app.ai.agents.investigation_report import validate_report
from app.ai.llm.base import LLMToolCall, LLMToolMessage, LLMToolResponse


class B2ReportReplayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.case_id, self.organization_id = UUID(int=101), UUID(int=102)
        self.workspace_id, self.order_id = UUID(int=103), UUID(int=104)
        self.as_of = datetime.fromisoformat("2026-10-19T15:01:09+00:00")
        events = [str(UUID(int=number)) for number in range(201, 205)]
        source = str(UUID(int=301))
        self.trace = [
            {"tool": "get_exception_case", "arguments": {"case_id": str(self.case_id)},
             "result": {"status": "found", "case": {"id": str(self.case_id),
                                                    "order_id": str(self.order_id),
                                                    "status": "open",
                                                    "problem_description": "Shipment timing review; cause unconfirmed."}}},
            {"tool": "analyze_fulfillment",
             "arguments": {"order_id": str(self.order_id), "as_of": self.as_of.isoformat()},
             "result": {"status": "found", "analysis": {
                 "order_id": str(self.order_id), "as_of": self.as_of.isoformat(),
                 "evidence_event_ids": events, "whole_order_completion": "unknown",
                 "shipment": {"status": "late", "scope": "shipment"},
                 "delivery": {"status": "on_time", "scope": "shipment"},
                 "allocation": {"status": "not_observed", "causal_status": "unknown",
                                "failure_event_ids": [], "failures": []}}}},
            {"tool": "search_knowledge", "arguments": {"query": "Shipment SOP"},
             "result": {"status": "found", "sources": [{"chunk_id": source,
                    "document_id": str(UUID(int=302)), "document_filename": "synthetic-sop.txt",
                    "content": "Compare same-shipment times; does not prove a cause.",
                    "page_number": 1}]}},
        ]
        self.bad = json.dumps({"outcome": "observed_delay", "evidence_event_ids": ["E3", "E4"],
                               "root_cause": "inventory_allocation_blocked",
                               "knowledge_source_ids": ["K1"]})
        self.mapping = core._report_reference_map(self.trace)

    def messages(self):
        messages = [LLMToolMessage(role="user", content=json.dumps({
            "task": "Investigate this exception", "case_id": str(self.case_id),
            "as_of": self.as_of.isoformat(), "require_knowledge": True,
        }))]
        for index, step in enumerate(self.trace, 1):
            call = LLMToolCall(str(index), step["tool"], step["arguments"])
            messages.extend([
                LLMToolMessage(role="assistant", tool_calls=[call]),
                LLMToolMessage(role="tool", content=json.dumps(step["result"]),
                               tool_call_id=str(index), tool_name=step["tool"]),
            ])
        messages.append(LLMToolMessage(role="user", content="Return the evidence report from observed tool results."))
        return messages

    def compact(self):
        return core._compact_observed_report(
            self.messages(), self.trace, organization_id=self.organization_id,
            case_id=self.case_id, order_id=self.order_id, as_of=self.as_of,
        )

    def corrected(self):
        return json.dumps({
            "outcome": "observed_delay", "evidence_event_ids": ["E1", "E2", "E3", "E4"],
            "root_cause": "unknown", "knowledge_source_ids": ["K1"],
        })

    def test_first_report_has_all_observations_labels_and_unknown_cause(self):
        compact = self.compact()
        self.assertEqual([message.role for message in compact], ["user"])
        data = json.loads(compact[0].content.split("\n", 1)[1])
        self.assertEqual(data["verified_tool_observations"], self.trace)
        self.assertEqual(data["required_report_citations"], {
            "evidence_event_ids": ["E1", "E2", "E3", "E4"], "knowledge_source_ids": ["K1"],
        })
        self.assertEqual(data["verified_report_requirements"], {
            "outcome": "observed_delay", "evidence_event_ids": ["E1", "E2", "E3", "E4"],
            "root_cause": "unknown", "knowledge_source_ids": ["K1"],
        })
        self.assertEqual(data["causal_basis"], {
            "allocation_status": "not_observed", "causal_status": "unknown",
        })
        self.assertIn("root_cause=unknown", core.SHORT_REPORT_BOUNDARY)

    def test_saved_bad_candidate_feedback_names_both_errors_and_keeps_context(self):
        feedback = core._short_report_correction_feedback(self.bad, self.trace)
        self.assertIn('"missing_evidence_event_ids": ["E1", "E2"]', feedback)
        self.assertIn('"root_cause": {"candidate": "inventory_allocation_blocked", "required": "unknown"}',
                      feedback)
        self.assertIn("do not repeat it unchanged", feedback)
        messages = self.messages() + [LLMToolMessage(role="assistant", content=self.bad),
                                      LLMToolMessage(role="user", content=feedback)]
        compact = core._compact_report_correction(
            messages, self.trace, rejected_content=self.bad,
            organization_id=self.organization_id, case_id=self.case_id,
            order_id=self.order_id, as_of=self.as_of,
        )
        self.assertEqual([message.role for message in compact], ["user", "assistant", "user"])
        self.assertEqual(compact[0], self.compact()[0])
        self.assertEqual(compact[-2].content, self.bad)
        self.assertEqual(compact[-1].content, feedback)

    def test_correct_report_passes_original_validator_but_each_error_is_rejected(self):
        report = validate_report(core._resolve_report_references(self.corrected(), self.trace), self.trace)
        self.assertEqual(report.root_cause, "unknown")
        self.assertEqual(len(report.evidence_event_ids), 4)
        self.assertEqual(len(report.knowledge_source_ids), 1)
        for candidate in (
            self.bad,
            json.dumps({**json.loads(self.corrected()), "evidence_event_ids": ["E3", "E4"]}),
            json.dumps({**json.loads(self.corrected()), "root_cause": "inventory_allocation_blocked"}),
        ):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                validate_report(core._resolve_report_references(candidate, self.trace), self.trace)

    async def test_graph_stops_after_same_invalid_correction(self):
        provider = SimpleNamespace(generate_with_tools=AsyncMock(side_effect=[
            LLMToolResponse(self.bad, "controlled", "stop"),
            LLMToolResponse(self.bad, "controlled", "stop"),
        ]))
        session = core_graph.CoreSession(
            provider=provider, db=MagicMock(), organization_id=self.organization_id,
            case_id=self.case_id, as_of=self.as_of, registry={}, definitions=[],
            workspace_id=self.workspace_id, require_knowledge=True, messages=self.messages(),
            trace=self.trace.copy(), order_id=self.order_id, final_only=True, requests=3,
        )
        await core_graph._model_decision({"session": session, "next_step": "decide"})
        self.assertEqual((await core_graph._validate_report({"session": session}))["next_step"], "decide")
        await core_graph._model_decision({"session": session, "next_step": "decide"})
        with self.assertRaises(core.CoreAgentError) as caught:
            await core_graph._validate_report({"session": session})
        self.assertEqual(caught.exception.error_code, "ungrounded_final")
        self.assertEqual(caught.exception.model_requests, 5)
        self.assertEqual([item["phase"] for item in session.rejected], ["report", "report"])
        first, correction = provider.generate_with_tools.call_args_list
        self.assertEqual(first.kwargs["tools"], [])
        self.assertEqual(correction.kwargs["tools"], [])
        self.assertEqual(first.kwargs["messages"], self.compact())
        self.assertEqual([message.role for message in correction.kwargs["messages"]],
                         ["user", "assistant", "user"])

    async def test_graph_accepts_corrected_report_without_rewriting_it(self):
        provider = SimpleNamespace(generate_with_tools=AsyncMock(side_effect=[
            LLMToolResponse(self.bad, "controlled", "stop"),
            LLMToolResponse(self.corrected(), "controlled", "stop"),
        ]))
        session = core_graph.CoreSession(
            provider=provider, db=MagicMock(), organization_id=self.organization_id,
            case_id=self.case_id, as_of=self.as_of, registry={}, definitions=[],
            workspace_id=self.workspace_id, require_knowledge=True, messages=self.messages(),
            trace=self.trace.copy(), order_id=self.order_id, final_only=True, requests=3,
        )
        await core_graph._model_decision({"session": session, "next_step": "decide"})
        self.assertEqual((await core_graph._validate_report({"session": session}))["next_step"], "decide")
        await core_graph._model_decision({"session": session, "next_step": "decide"})
        self.assertEqual((await core_graph._validate_report({"session": session}))["next_step"], "end")
        self.assertEqual(session.result.report["root_cause"], "unknown")
        self.assertEqual(set(session.result.report["evidence_event_ids"]),
                         set(self.mapping["evidence_event_ids"].values()))
        self.assertEqual(session.result.report["knowledge_source_ids"],
                         list(self.mapping["knowledge_source_ids"].values()))
        self.assertEqual(session.result.model_final, self.corrected())
        self.assertEqual(len(session.rejected), 1)
