"""Offline report-contract check and one guarded model probe from retained observations.

No database, retrieval, investigation API, or business write is opened here.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/investigation_allocation_run_20261020T200910720967Z_e78899e0.json"
CHECK = ROOT / "scripts/investigation_allocation_report_compaction_check_20261021.json"
PROBE = ROOT / "scripts/investigation_allocation_report_probe_20261021.json"
ALIGNED_CHECK = ROOT / "scripts/investigation_allocation_report_aligned_check_20261021.json"
ALIGNED_PROBE = ROOT / "scripts/investigation_allocation_report_aligned_probe_20261021.json"
STAGE_CHECK = ROOT / "scripts/investigation_allocation_report_stage_check_20261021.json"
STAGE_PROBE = ROOT / "scripts/investigation_allocation_report_stage_short_refs_20261021.json"
STAGE_COMPACTION_CHECK = ROOT / "scripts/investigation_allocation_report_stage_compaction_check_20261021.json"
SHORT_CHECK = ROOT / "scripts/investigation_allocation_report_short_refs_check_20261021.json"
SOURCE_REQUEST_ID = "2b4100f8-8fc2-41f5-ac77-35695c4ae23e"

os.environ["DATABASE_URL"] = "postgresql+asyncpg://offline:offline@127.0.0.1:5433/ragforge_day6_test"
sys.path.insert(0, str(ROOT / "backend"))

from app.ai.agents import core_agent as core
from app.ai.agents import core_graph as graph
from app.ai.agents.investigation_report import (
    evidence_contract,
    render_report,
    validate_report,
)
from app.ai.llm.base import LLMToolCall, LLMToolMessage, LLMToolResponse
from app.ai.llm.ollama_provider import (
    OllamaProvider,
    _to_ollama_tool_messages,
)
from app.core.config import settings
from pydantic import ValidationError


def configure_like_allocation_api() -> None:
    # The isolated API calls this same configure() in serve(), before creating the Provider.
    import investigation_allocation_demo as allocation_demo

    state = allocation_demo.state_read()
    allocation_demo.configure(state)
    if settings.LLM_REQUEST_TIMEOUT_SECONDS <= core.MODEL_TIMEOUT_SECONDS:
        raise RuntimeError("Provider HTTP timeout must outlast the Graph's model deadline")


def exception_chain(exc: BaseException) -> list[str]:
    """Persist exception types only; upstream messages may contain private URLs."""
    chain, seen = [], set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        chain.append(type(exc).__name__)
        exc = exc.__cause__ if exc.__cause__ is not None else exc.__context__
    return chain


class StageProvider:
    """Record only actual request parameters before delegating to the real Provider."""

    def __init__(self, inner: OllamaProvider, evidence: dict):
        self.inner = inner
        self.evidence = evidence

    async def generate_with_tools(self, **kwargs):
        round_result = self.evidence["rounds"][-1]
        round_result["sent"] = {
            "model": settings.LLM_MODEL,
            "message_roles": [message.role for message in kwargs["messages"]],
            "wire_utf8_bytes": len(json.dumps(
                _to_ollama_tool_messages(kwargs["messages"], kwargs["system"]),
                ensure_ascii=False,
            ).encode("utf-8")),
            "tool_names": [tool.name for tool in kwargs["tools"]],
            "max_tokens_argument": kwargs["max_tokens"],
            "effective_num_predict": kwargs["max_tokens"] or settings.LLM_MAX_TOKENS,
            "provider_http_timeout_seconds": settings.LLM_REQUEST_TIMEOUT_SECONDS,
            "graph_model_deadline_seconds": core.MODEL_TIMEOUT_SECONDS,
        }
        save_update(STAGE_PROBE, self.evidence)
        response = await self.inner.generate_with_tools(**kwargs)
        round_result["raw_response"] = response.content
        round_result["stop_reason"] = response.stop_reason
        round_result["tool_calls"] = [call.name for call in response.tool_calls]
        round_result["input_tokens"] = response.usage.input_tokens
        round_result["output_tokens"] = response.usage.output_tokens
        round_result["server_timing_ns"] = response.server_timing_ns
        save_update(STAGE_PROBE, self.evidence)  # Before parsing or validation.
        return response


def save_once(path: Path, data: dict) -> None:
    with path.open("x", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())


def save_update(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())


def prepare() -> tuple[dict, list[LLMToolMessage], list[LLMToolMessage], str]:
    evidence = json.loads(SOURCE.read_text(encoding="utf-8"))
    trace = evidence["trace"]
    if (evidence["request_id"] != SOURCE_REQUEST_ID
            or evidence["error_code"] != "model_timeout"
            or [step["tool"] for step in trace]
            != ["get_exception_case", "analyze_fulfillment", "search_knowledge"]
            or any(step["result"]["status"] != "found" for step in trace)
            or not evidence["require_knowledge"]):
        raise RuntimeError("Retained source does not match the expected failed report turn")
    request = {"task": "Investigate this exception", "case_id": evidence["case_id"],
               "as_of": evidence["as_of"], "require_knowledge": True}
    history = [LLMToolMessage(role="user", content=json.dumps(request))]
    for index, step in enumerate(trace, 1):
        call = LLMToolCall(f"reconstructed_{index}", step["tool"], step["arguments"])
        history.extend([
            LLMToolMessage(role="assistant", tool_calls=[call]),
            LLMToolMessage(role="tool", content=json.dumps(step["result"], allow_nan=False),
                           tool_call_id=call.id, tool_name=call.name),
        ])
    history.append(LLMToolMessage(role="user", content="Return the evidence report from observed tool results."))
    compact = core._compact_observed_report(
        history, trace, organization_id=UUID(evidence["organization_id"]),
        case_id=UUID(evidence["case_id"]),
        order_id=UUID(trace[0]["result"]["case"]["order_id"]),
        as_of=datetime.fromisoformat(evidence["as_of"]),
    )
    if compact is None:
        raise RuntimeError("Clean report turn was not compacted")
    system = core.KNOWLEDGE_REPORT_SYSTEM + core.REPORT_DATA_BOUNDARY
    return evidence, history, compact, system


def check(*, aligned: bool = False) -> dict:
    if aligned:
        configure_like_allocation_api()
    evidence, history, compact, system = prepare()
    trace = evidence["trace"]
    wire = _to_ollama_tool_messages(compact, system)
    payload = json.loads(compact[0].content.split("\n", 1)[1])
    if (len(wire) != 2 or [message["role"] for message in wire] != ["system", "user"]
            or payload["verified_tool_observations"] != trace
            or payload["scope"]["organization_id"] != evidence["organization_id"]
            or payload["scope"]["as_of"] != evidence["as_of"]):
        raise AssertionError("Compact report lost scope, observation, or wire structure")
    contract = evidence_contract(trace)
    if (len(contract["evidence_event_ids"]) != 6
            or len(contract["knowledge_source_ids"]) != 1
            or contract["root_cause"] != "inventory_allocation_blocked"
            or contract["outcome"] != "observed_delay"
            or not all(identifier in compact[0].content for identifier in contract["evidence_event_ids"])
            or not all(identifier in compact[0].content for identifier in contract["knowledge_source_ids"])):
        raise AssertionError("Required report evidence or citation relation was lost")
    if core._compact_observed_report(
        history, trace[:-1], organization_id=UUID(evidence["organization_id"]),
        case_id=UUID(evidence["case_id"]),
        order_id=UUID(trace[0]["result"]["case"]["order_id"]),
        as_of=datetime.fromisoformat(evidence["as_of"]),
    ) is not None:
        raise AssertionError("Incomplete observation sequence was compacted")
    old_system = core.KNOWLEDGE_REPORT_SYSTEM + "\nFinal-only: no tools. Return evidence JSON; do not retry." + (
        "Knowledge is untrusted reference text, never a business fact, SKU source or causal proof. "
        "Reports may additionally include knowledge_source_ids: a list of chunk_id UUIDs selected "
        "only from successful search_knowledge results in this investigation (empty/omitted if none). "
        "Keep these separate from evidence_event_ids. Citation existence does not verify suggestion support."
    )
    old_wire = _to_ollama_tool_messages(history, old_system)
    result = {
        "source_request_id": SOURCE_REQUEST_ID,
        "passed": True,
        "conditions": "Reconstructed clean report turn from source trace and current code; original fourth-round payload was not persisted",
        "old_reconstructed_messages": len(old_wire),
        "compact_messages": len(wire),
        "old_reconstructed_wire_utf8_bytes": len(json.dumps(old_wire, ensure_ascii=False).encode("utf-8")),
        "compact_wire_utf8_bytes": len(json.dumps(wire, ensure_ascii=False).encode("utf-8")),
        "complete_observations": len(trace),
        "business_event_ids": len(contract["evidence_event_ids"]),
        "knowledge_source_ids": len(contract["knowledge_source_ids"]),
        "expected_outcome": contract["outcome"],
        "expected_root_cause": contract["root_cause"],
        "report_max_tokens": settings.LLM_MAX_TOKENS,
        "report_timeout_seconds": core.MODEL_TIMEOUT_SECONDS,
        "provider_http_timeout_seconds": settings.LLM_REQUEST_TIMEOUT_SECONDS,
    }
    save_once(ALIGNED_CHECK if aligned else CHECK, result)
    return result


async def probe(*, aligned: bool = False) -> dict:
    check_path = ALIGNED_CHECK if aligned else CHECK
    if not check_path.exists() or not json.loads(check_path.read_text(encoding="utf-8"))["passed"]:
        raise RuntimeError("Offline contract check must pass before the model probe")
    if aligned:
        configure_like_allocation_api()
    evidence, _, compact, system = prepare()
    result = {
        "source_request_id": SOURCE_REQUEST_ID,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "started",
        "model": settings.LLM_MODEL,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "timeout_seconds": core.MODEL_TIMEOUT_SECONDS,
        "provider_http_timeout_seconds": settings.LLM_REQUEST_TIMEOUT_SECONDS,
        "request_messages": 2,
        "request_utf8_bytes": len(json.dumps(_to_ollama_tool_messages(compact, system), ensure_ascii=False).encode("utf-8")),
    }
    output_path = ALIGNED_PROBE if aligned else PROBE
    save_once(output_path, result)  # This guard is written before the only model call.
    provider = OllamaProvider()
    started = time.perf_counter()
    try:
        response = await asyncio.wait_for(provider.generate_with_tools(
            messages=compact, tools=[], system=system, max_tokens=None,
        ), timeout=core.MODEL_TIMEOUT_SECONDS)
        result.update({"status": "returned", "stop_reason": response.stop_reason,
                       "tool_calls": [call.name for call in response.tool_calls],
                       "model_response": response.content,
                       "input_tokens": response.usage.input_tokens,
                       "output_tokens": response.usage.output_tokens,
                       "server_timing_ns": response.server_timing_ns,
                       "exception_chain_types": []})
        if response.tool_calls or response.stop_reason == "max_tokens":
            result["status"] = "invalid_response"
        else:
            try:
                report = validate_report(response.content, evidence["trace"])
                expected_sources = set(evidence_contract(evidence["trace"])["knowledge_source_ids"])
                if {str(identifier) for identifier in report.knowledge_source_ids} != expected_sources:
                    raise ValueError("Required retrieved SOP source was not cited separately")
                handoff = render_report(report, evidence["trace"])
                if not all(f"{index}. " in handoff for index in range(1, 7)):
                    raise ValueError("Six-part handoff is incomplete")
                result["report"] = report.model_dump(mode="json")
                result["rendered_report"] = handoff
                result["status"] = "validated_report"
            except (ValueError, TypeError) as exc:
                result["status"] = "report_rejected"
                result["validation_exception_type"] = type(exc).__name__
                result["validation_error"] = str(exc)
    except TimeoutError as exc:
        result["status"] = "model_timeout"
        result["exception_chain_types"] = exception_chain(exc)
    except Exception as exc:  # noqa: BLE001 - record the sole probe's actual failure
        result["status"] = "model_error"
        result["exception_type"] = type(exc).__name__
        result["exception_chain_types"] = exception_chain(exc)
    finally:
        result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        result["finished_at"] = datetime.now(UTC).isoformat()
        await provider._client.aclose()
        save_update(output_path, result)
    return result


def stage_check() -> dict:
    configure_like_allocation_api()
    evidence, _, compact, system = prepare()
    trace = evidence["trace"]
    contract = evidence_contract(trace)
    payload = json.loads(compact[0].content.split("\n", 1)[1])
    if (payload["required_report_citations"]["evidence_event_ids"] != contract["evidence_event_ids"]
            or payload["required_report_citations"]["knowledge_source_ids"]
            != contract["knowledge_source_ids"]
            or payload["verified_tool_observations"] != trace
            or len(_to_ollama_tool_messages(compact, system)) != 2
            or settings.LLM_REQUEST_TIMEOUT_SECONDS != 190
            or settings.LLM_MAX_TOKENS != 700
            or core.MODEL_TIMEOUT_SECONDS != 180):
        raise AssertionError("Report input, scope, or effective configuration differs")
    bad = dict(contract)
    bad["evidence_event_ids"] = [contract["evidence_event_ids"][0]] * 2 + [
        "00000000-0000-0000-0000-000000000000",
    ]
    bad["knowledge_source_ids"] = []
    bad_text = json.dumps(bad)
    difference = core._report_citation_diff(bad_text, trace)
    feedback = core._report_correction_feedback(bad_text, trace)
    if (len(difference["missing_evidence_event_ids"]) != 5
            or len(difference["duplicate_evidence_event_ids"]) != 1
            or len(difference["unobserved_evidence_event_ids"]) != 1
            or difference["missing_knowledge_source_ids"] != contract["knowledge_source_ids"]
            or not all(identifier in feedback for identifier in difference["missing_evidence_event_ids"])
            or not all(identifier in feedback for identifier in contract["knowledge_source_ids"])):
        raise AssertionError("Citation feedback omitted a real difference")
    try:
        validate_report(bad_text, trace)
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid citations unexpectedly passed the original validator")
    valid = validate_report(json.dumps(contract), trace)
    handoff = render_report(valid, trace)
    if not all(f"{index}. " in handoff for index in range(1, 7)):
        raise AssertionError("Valid report does not render six sections")
    result = {"passed": True, "source_request_id": SOURCE_REQUEST_ID,
              "business_ids": len(contract["evidence_event_ids"]),
              "sop_ids": len(contract["knowledge_source_ids"]),
              "missing_feedback_count": len(difference["missing_evidence_event_ids"]),
              "duplicate_feedback_count": len(difference["duplicate_evidence_event_ids"]),
              "unobserved_feedback_count": len(difference["unobserved_evidence_event_ids"]),
              "provider_http_timeout_seconds": settings.LLM_REQUEST_TIMEOUT_SECONDS,
              "per_model_deadline_seconds": core.MODEL_TIMEOUT_SECONDS,
              "report_num_predict": settings.LLM_MAX_TOKENS,
              "model_budget": core.MAX_MODEL_REQUESTS,
              "completed_business_requests": 3,
              "maximum_report_requests": 2,
              "stage_deadline_seconds": 690}
    save_once(STAGE_CHECK, result)
    return result


async def stage_compaction_check() -> dict:
    evidence, history, _, _ = prepare()
    contract = evidence_contract(evidence["trace"])
    invalid = dict(contract)
    invalid["evidence_event_ids"] = contract["evidence_event_ids"][:2]
    bad_text = json.dumps(invalid)

    async def replay(second: str):
        class OfflineProvider:
            def __init__(self):
                self.requests = []

            async def generate_with_tools(self, **kwargs):
                self.requests.append(kwargs)
                content = bad_text if len(self.requests) == 1 else second
                return LLMToolResponse(content=content, model="offline", stop_reason="stop")

        provider = OfflineProvider()
        session = graph.CoreSession(
            provider=provider, db=None,
            organization_id=UUID(evidence["organization_id"]),
            case_id=UUID(evidence["case_id"]), as_of=datetime.fromisoformat(evidence["as_of"]),
            registry={}, definitions=[], workspace_id=UUID(evidence["workspace_id"]),
            require_knowledge=True, messages=list(history), trace=evidence["trace"],
            order_id=UUID(evidence["trace"][0]["result"]["case"]["order_id"]),
            final_only=True, requests=3,
        )
        assert (await graph._model_decision({"session": session}))["next_step"] == "report"
        assert (await graph._validate_report({"session": session}))["next_step"] == "decide"
        assert session.invalid_responses["report"] == 1
        assert all(identifier in session.messages[-1].content
                   for identifier in contract["evidence_event_ids"][2:])
        assert (await graph._model_decision({"session": session}))["next_step"] == "report"
        first, correction = provider.requests
        assert [message.role for message in first["messages"]] == ["user"]
        assert [message.role for message in correction["messages"]] == ["user", "assistant", "user"]
        assert correction["messages"][0].content == first["messages"][0].content
        assert correction["messages"][1].content == bad_text
        assert correction["messages"][2].content == core._report_correction_feedback(
            bad_text, evidence["trace"],
        )
        assert first["tools"] == correction["tools"] == []
        assert first["max_tokens"] is correction["max_tokens"] is None
        assert first["system"] == correction["system"]
        assert len(_to_ollama_tool_messages(correction["messages"], correction["system"])) == 4
        return provider, session

    provider, session = await replay(json.dumps(contract))
    assert (await graph._validate_report({"session": session}))["next_step"] == "end"
    assert session.result.report["evidence_event_ids"] == contract["evidence_event_ids"]
    assert session.result.report["knowledge_source_ids"] == contract["knowledge_source_ids"]
    assert session.requests == 5
    _, failed_session = await replay(bad_text)
    try:
        await graph._validate_report({"session": failed_session})
    except core.CoreAgentError as exc:
        assert exc.error_code == "ungrounded_final"
    else:
        raise AssertionError("A second invalid report passed the original validator")
    result = {"passed": True, "source_request_id": SOURCE_REQUEST_ID,
              "first_request_roles": [message.role for message in provider.requests[0]["messages"]],
              "correction_request_roles": [message.role for message in provider.requests[1]["messages"]],
              "complete_observations": len(evidence["trace"]),
              "business_citations": len(contract["evidence_event_ids"]),
              "sop_citations": len(contract["knowledge_source_ids"]),
              "corrected_report_validated": True,
              "second_bad_report_rejected_as": "ungrounded_final",
              "requests_after_one_repair": session.requests,
              "model_calls": 0, "database_or_retrieval_calls": 0}
    save_once(STAGE_COMPACTION_CHECK, result)
    return result


async def short_ref_check() -> dict:
    """Exercise the exact Graph report boundary with saved observations and no model."""
    configure_like_allocation_api()
    evidence, history, compact, _ = prepare()
    trace = evidence["trace"]
    mapping = core._report_reference_map(trace)
    data = json.loads(compact[0].content.split("\n", 1)[1])
    assert data["verified_tool_observations"] == trace
    assert data["required_report_citations"] == {field: list(labels) for field, labels in mapping.items()}
    assert len(mapping["evidence_event_ids"]) == 6 and len(mapping["knowledge_source_ids"]) == 1
    valid = {**evidence_contract(trace),
             "evidence_event_ids": list(mapping["evidence_event_ids"]),
             "knowledge_source_ids": list(mapping["knowledge_source_ids"])}
    valid_text = json.dumps(valid)
    resolved = core._resolve_report_references(valid_text, trace)
    assert validate_report(resolved, trace).model_dump(mode="json") == evidence_contract(trace)
    cases = {
        "missing_event": {**valid, "evidence_event_ids": valid["evidence_event_ids"][:-1]},
        "missing_source": {**valid, "knowledge_source_ids": []},
        "unknown_event": {**valid, "evidence_event_ids": [*valid["evidence_event_ids"], "E7"]},
        "unknown_source": {**valid, "knowledge_source_ids": ["K2"]},
        "mixed_event": {**valid, "evidence_event_ids": [*valid["evidence_event_ids"], "K1"]},
        "mixed_source": {**valid, "knowledge_source_ids": ["E1"]},
        "duplicate_event": {**valid, "evidence_event_ids": [*valid["evidence_event_ids"], "E1"]},
        "duplicate_source": {**valid, "knowledge_source_ids": ["K1", "K1"]},
        "raw_uuid": {**valid, "evidence_event_ids": list(mapping["evidence_event_ids"].values())},
    }
    differences = {}
    for name, candidate in cases.items():
        content = json.dumps(candidate)
        differences[name] = core._short_report_citation_diff(content, trace)
        try:
            core._resolve_report_references(content, trace)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid short-reference candidate passed: {name}")

    class OfflineProvider:
        def __init__(self):
            self.requests = []

        async def generate_with_tools(self, **kwargs):
            self.requests.append(kwargs)
            content = json.dumps(cases["missing_event"]) if len(self.requests) == 1 else valid_text
            return LLMToolResponse(content=content, model="offline", stop_reason="stop")

    provider = OfflineProvider()
    session = graph.CoreSession(
        provider=provider, db=None, organization_id=UUID(evidence["organization_id"]),
        case_id=UUID(evidence["case_id"]), as_of=datetime.fromisoformat(evidence["as_of"]),
        registry={}, definitions=[], workspace_id=UUID(evidence["workspace_id"]),
        require_knowledge=True, messages=list(history), trace=trace,
        order_id=UUID(trace[0]["result"]["case"]["order_id"]), final_only=True, requests=3,
    )
    for index in (1, 2):
        assert (await graph._model_decision({"session": session}))["next_step"] == "report"
        next_step = (await graph._validate_report({"session": session}))["next_step"]
        assert next_step == ("decide" if index == 1 else "end")
    first, correction = provider.requests
    assert [message.role for message in first["messages"]] == ["user"]
    assert [message.role for message in correction["messages"]] == ["user", "assistant", "user"]
    assert first["messages"][0].content == correction["messages"][0].content
    assert "E6" in correction["messages"][-1].content and "K1" in first["messages"][0].content
    assert session.result.report == evidence_contract(trace)
    assert all(f"{section}. " in session.result.answer for section in range(1, 7))
    result = {"passed": True, "source_request_id": SOURCE_REQUEST_ID,
              "citation_reference_map": mapping,
              "business_refs": len(mapping["evidence_event_ids"]),
              "knowledge_refs": len(mapping["knowledge_source_ids"]),
              "rejected_cases": list(cases), "differences": differences,
              "first_request_roles": [message.role for message in first["messages"]],
              "correction_request_roles": [message.role for message in correction["messages"]],
              "corrected_uuid_report_validated": True,
              "model_calls": 0, "database_or_retrieval_calls": 0}
    save_once(SHORT_CHECK, result)
    return result


async def stage_probe() -> dict:
    check = json.loads(SHORT_CHECK.read_text(encoding="utf-8"))
    if not check["passed"] or check["source_request_id"] != SOURCE_REQUEST_ID:
        raise RuntimeError("Matching offline stage check is required")
    configure_like_allocation_api()
    evidence, history, _, _ = prepare()
    result = {"source_request_id": SOURCE_REQUEST_ID,
              "started_at": datetime.now(UTC).isoformat(),
              "status": "started", "phase": "report",
              "stage_deadline_seconds": 690,
              "per_model_deadline_seconds": core.MODEL_TIMEOUT_SECONDS,
              "provider_http_timeout_seconds": settings.LLM_REQUEST_TIMEOUT_SECONDS,
              "report_num_predict": settings.LLM_MAX_TOKENS,
              "model_budget": core.MAX_MODEL_REQUESTS,
              "completed_business_requests": 3,
              "citation_reference_map": core._report_reference_map(evidence["trace"]),
              "rounds": []}
    save_once(STAGE_PROBE, result)  # Guard before any model request.
    inner = OllamaProvider()
    session = graph.CoreSession(
        provider=StageProvider(inner, result), db=None,
        organization_id=UUID(evidence["organization_id"]),
        case_id=UUID(evidence["case_id"]), as_of=datetime.fromisoformat(evidence["as_of"]),
        registry={}, definitions=[], workspace_id=UUID(evidence["workspace_id"]),
        require_knowledge=True, messages=history, trace=evidence["trace"],
        order_id=UUID(evidence["trace"][0]["result"]["case"]["order_id"]),
        final_only=True, requests=3,
    )
    started = time.perf_counter()
    try:
        async with asyncio.timeout(690):
            for index in (1, 2):
                round_result = {"index": index, "started_at": datetime.now(UTC).isoformat(),
                                "status": "model_started"}
                result["rounds"].append(round_result)
                save_update(STAGE_PROBE, result)
                round_started = time.perf_counter()
                try:
                    route = await graph._model_decision({"session": session})
                finally:
                    round_result["elapsed_seconds"] = round(time.perf_counter() - round_started, 3)
                    save_update(STAGE_PROBE, result)
                response = session.response
                if route["next_step"] != "report" or response.tool_calls:
                    round_result["status"] = "invalid_report_protocol"
                    result["status"] = "failed"
                    break
                try:
                    round_result["candidate_json"] = json.loads(response.content)
                except (TypeError, ValueError) as exc:
                    round_result["candidate_json_error_type"] = type(exc).__name__
                round_result["citation_differences"] = core._short_report_citation_diff(
                    response.content, session.trace,
                )
                save_update(STAGE_PROBE, result)
                try:
                    validate_report(core._resolve_report_references(response.content, session.trace),
                                    session.trace)
                except (ValidationError, ValueError) as exc:
                    round_result["validation_error_type"] = type(exc).__name__
                    round_result["validation_error"] = str(exc)
                route = await graph._validate_report({"session": session})
                if route["next_step"] == "end":
                    expected = set(evidence_contract(session.trace)["knowledge_source_ids"])
                    actual = {str(value) for value in session.result.report.get("knowledge_source_ids", [])}
                    if actual == expected and all(
                        f"{section}. " in session.result.answer for section in range(1, 7)
                    ):
                        round_result["status"] = "validated_report"
                        result["status"] = "validated_report"
                        result["report"] = session.result.report
                        result["rendered_report"] = session.result.answer
                        break
                    round_result["status"] = "scenario_citation_rejected"
                    round_result["validation_error"] = "Retrieved SOP source or six-part handoff missing"
                    session.result = None
                    session.rejected.append({"content": response.content,
                                             "reason": "required_sop_or_handoff", "phase": "report"})
                    session.invalid_responses["report"] += 1
                    session.messages.extend([
                        LLMToolMessage(role="assistant", content=response.content),
                        LLMToolMessage(role="user", content=core._short_report_correction_feedback(
                            response.content, session.trace,
                        )),
                    ])
                else:
                    round_result["status"] = "report_rejected"
                    round_result["feedback"] = session.messages[-1].content
                save_update(STAGE_PROBE, result)
                if index == 2:
                    result["status"] = "failed_after_one_correction"
            else:
                result["status"] = "failed_after_one_correction"
    except core.CoreAgentError as exc:
        result["status"] = "core_error"
        result["error_code"] = exc.error_code
        result["exception_chain_types"] = exception_chain(exc)
        if result["rounds"]:
            result["rounds"][-1]["status"] = "core_error"
    except TimeoutError as exc:
        result["status"] = "stage_timeout"
        result["exception_chain_types"] = exception_chain(exc)
        if result["rounds"]:
            result["rounds"][-1]["status"] = "stage_timeout"
    except Exception as exc:  # noqa: BLE001 - preserve exact unexpected failure class
        result["status"] = "stage_error"
        result["exception_chain_types"] = exception_chain(exc)
        if result["rounds"]:
            result["rounds"][-1]["status"] = "stage_error"
    finally:
        result["model_requests_used"] = session.requests - 3
        result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        result["finished_at"] = datetime.now(UTC).isoformat()
        await inner._client.aclose()
        save_update(STAGE_PROBE, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=(
        "check", "probe", "aligned-check", "aligned-probe", "stage-check", "stage-probe",
        "stage-compaction-check", "short-ref-check",
    ))
    args = parser.parse_args()
    aligned = args.mode.startswith("aligned-")
    if args.mode == "stage-check":
        outcome = stage_check()
    elif args.mode == "stage-compaction-check":
        outcome = asyncio.run(stage_compaction_check())
    elif args.mode == "short-ref-check":
        outcome = asyncio.run(short_ref_check())
    elif args.mode == "stage-probe":
        outcome = asyncio.run(stage_probe())
    else:
        outcome = check(aligned=aligned) if args.mode.endswith("check") else asyncio.run(probe(aligned=aligned))
    print(json.dumps({key: value for key, value in outcome.items()
                      if key not in ("report", "rendered_report", "model_response", "rounds")},
                     ensure_ascii=False))
