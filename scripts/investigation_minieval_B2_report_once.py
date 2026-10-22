"""One real report-stage attempt from saved B2 observations; no business reads."""

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
SOURCE = ROOT / "scripts/investigation_minieval_B2_once.json"
STEM = ROOT / "scripts/investigation_minieval_B2_report_once"
SOURCE_REQUEST_ID = "11ddcf04-820f-42b7-80d2-0e7141df21af"

# The retained fixture module pins a URL at import, but this script never opens a DB session.
os.environ.setdefault("POSTGRES_PASSWORD", "offline-report-stage-only")
os.environ.setdefault("SECRET_KEY", "offline-report-stage-only-not-for-auth")
sys.path.insert(0, str(ROOT / "backend"))

import investigation_page_demo as page
from app.ai.agents import core_agent as core
from app.ai.agents import core_graph as graph
from app.ai.agents.investigation_report import evidence_contract, validate_report
from app.ai.llm.base import LLMToolCall, LLMToolMessage
from app.ai.llm.ollama_provider import OllamaProvider, _to_ollama_tool_messages
from app.core.config import settings
from pydantic import ValidationError


def exception_types(exc):
    chain, seen = [], set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        chain.append(type(exc).__name__)
        exc = exc.__cause__ if exc.__cause__ is not None else exc.__context__
    return chain


def prepare():
    saved = json.loads(SOURCE.read_text(encoding="utf-8"))
    trace = saved["trace"]
    if (saved["request_id"] != SOURCE_REQUEST_ID or saved["case_key"] != "B2"
            or saved["attempt_status"] != "finished" or saved["error_code"] != "ungrounded_final"
            or saved["model"] != "llama3.1:8b" or not saved["require_knowledge"]
            or [step["tool"] for step in trace]
            != ["get_exception_case", "analyze_fulfillment", "search_knowledge"]
            or any(step["result"]["status"] != "found" for step in trace)):
        raise RuntimeError("Saved B2 observations do not match the guarded report-only input")
    state = page.state_read()  # Local fixture identity only; no database query.
    if (state["case_id"] != saved["case_id"]
            or state["organization_id"] != saved["organization_id"]
            or state["workspace_id"] != saved["workspace_id"]):
        raise RuntimeError("Retained B2 scope differs from saved observations")
    page.configure(state["collection"])
    if (settings.LLM_PROVIDER != "ollama" or settings.LLM_MODEL != saved["model"]
            or settings.LLM_MAX_TOKENS != 700
            or settings.LLM_REQUEST_TIMEOUT_SECONDS != 190
            or core.MODEL_TIMEOUT_SECONDS != 180
            or settings.LLM_REQUEST_TIMEOUT_SECONDS <= core.MODEL_TIMEOUT_SECONDS):
        raise RuntimeError("Current provider or report deadline differs from B2 investigation")
    contract = evidence_contract(trace)
    if (contract["outcome"], contract["root_cause"]) != ("observed_delay", "unknown"):
        raise RuntimeError("Saved B2 causal contract differs")
    request = {"task": "Investigate this exception", "case_id": saved["case_id"],
               "as_of": saved["as_of"], "require_knowledge": True}
    history = [LLMToolMessage(role="user", content=json.dumps(request))]
    for index, step in enumerate(trace, 1):
        call = LLMToolCall(f"saved_{index}", step["tool"], step["arguments"])
        history.extend([
            LLMToolMessage(role="assistant", tool_calls=[call]),
            LLMToolMessage(role="tool", content=json.dumps(step["result"], allow_nan=False),
                           tool_call_id=call.id, tool_name=call.name),
        ])
    history.append(LLMToolMessage(role="user", content="Return the evidence report from observed tool results."))
    compact = core._compact_observed_report(
        history, trace, organization_id=UUID(saved["organization_id"]),
        case_id=UUID(saved["case_id"]),
        order_id=UUID(trace[0]["result"]["case"]["order_id"]),
        as_of=datetime.fromisoformat(saved["as_of"]),
    )
    if compact is None:
        raise RuntimeError("Saved observations cannot enter the current compact report path")
    report_data = json.loads(compact[0].content.split("\n", 1)[1])
    if (report_data["verified_tool_observations"] != trace
            or report_data["verified_report_requirements"] != {
                **contract,
                "evidence_event_ids": [f"E{i}" for i in range(1, len(contract["evidence_event_ids"]) + 1)],
                "knowledge_source_ids": [f"K{i}" for i in range(1, len(contract["knowledge_source_ids"]) + 1)],
            }):
        raise RuntimeError("Report context omitted saved observations or verified requirements")
    return saved, history, contract


class Evidence:
    def __init__(self, saved, contract):
        self.snapshot = STEM.with_suffix(".json")
        self.events = STEM.with_suffix(".jsonl")
        self.active = STEM.with_suffix(".active")
        if any(path.exists() for path in (self.snapshot, self.events, self.active,
                                           ROOT / "scripts/investigation_minieval.active")):
            raise RuntimeError("An evaluation is active or B2 report evidence already exists; no model call")
        with self.active.open("x", encoding="utf-8") as stream:
            stream.write(datetime.now(UTC).isoformat())
        try:
            self.data = {
                "source_request_id": saved["request_id"], "source_case_key": "B2",
                "source_evidence": str(SOURCE.relative_to(ROOT)),
                "started_at": datetime.now(UTC).isoformat(), "status": "reserved",
                "result_class": None, "provider_kind": "real_ollama",
                "model": settings.LLM_MODEL, "report_max_tokens": settings.LLM_MAX_TOKENS,
                "provider_http_timeout_seconds": settings.LLM_REQUEST_TIMEOUT_SECONDS,
                "per_model_deadline_seconds": core.MODEL_TIMEOUT_SECONDS,
                "stage_deadline_seconds": 690,
                "saved_observations": saved["trace"],
                "verified_contract": contract,
                "reference_map": core._report_reference_map(saved["trace"]),
                "rounds": [], "events_path": str(self.events.relative_to(ROOT)),
            }
            with self.snapshot.open("x", encoding="utf-8") as stream:
                json.dump(self.data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            with self.events.open("x", encoding="utf-8"):
                pass
        except BaseException:
            self.active.unlink(missing_ok=True)
            raise

    def save(self):
        temporary = self.snapshot.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(self.data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.snapshot)

    def emit(self, event, **values):
        with self.events.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": datetime.now(UTC).isoformat(), "event": event,
                                     **values}, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


class RecordingProvider:
    def __init__(self, inner, evidence):
        self.inner = inner
        self.evidence = evidence

    async def generate_with_tools(self, **kwargs):
        round_data = self.evidence.data["rounds"][-1]
        round_data["request"] = {
            "model": settings.LLM_MODEL, "messages": _to_ollama_tool_messages(
                kwargs["messages"], kwargs["system"]),
            "tools": [tool.name for tool in kwargs["tools"]],
            "options": {"num_predict": kwargs["max_tokens"] or settings.LLM_MAX_TOKENS,
                        "temperature": 0},
            "max_tokens_argument": kwargs["max_tokens"],
        }
        self.evidence.save()
        self.evidence.emit("model_request_sent", index=round_data["index"])
        response = await self.inner.generate_with_tools(**kwargs)
        round_data.update(raw_candidate=response.content, stop_reason=response.stop_reason,
                          tool_calls=[call.name for call in response.tool_calls],
                          input_tokens=response.usage.input_tokens,
                          output_tokens=response.usage.output_tokens,
                          server_timing_ns=response.server_timing_ns)
        self.evidence.save()  # Raw response survives any later parser or validator failure.
        self.evidence.emit("model_response_saved", index=round_data["index"])
        return response


async def run():
    saved, history, contract = prepare()
    evidence = Evidence(saved, contract)
    inner = OllamaProvider()
    session = graph.CoreSession(
        provider=RecordingProvider(inner, evidence), db=None,
        organization_id=UUID(saved["organization_id"]), case_id=UUID(saved["case_id"]),
        as_of=datetime.fromisoformat(saved["as_of"]), registry={}, definitions=[],
        workspace_id=UUID(saved["workspace_id"]), require_knowledge=True,
        messages=history, trace=saved["trace"],
        order_id=UUID(saved["trace"][0]["result"]["case"]["order_id"]),
        final_only=True, requests=3,
    )
    started = time.perf_counter()
    evidence.data["status"] = "running"
    evidence.save()
    try:
        async with asyncio.timeout(690):
            for index in (1, 2):
                round_data = {"index": index, "phase": "report", "started_at": datetime.now(UTC).isoformat()}
                evidence.data["rounds"].append(round_data)
                evidence.save()
                round_started = time.perf_counter()
                try:
                    route = await graph._model_decision({"session": session, "next_step": "decide"})
                finally:
                    round_data["elapsed_seconds"] = round(time.perf_counter() - round_started, 3)
                    evidence.save()
                if route["next_step"] != "report" or session.response.tool_calls:
                    round_data["status"] = "invalid_report_protocol"
                    evidence.data["error_code"] = "invalid_report_protocol"
                    break
                candidate = session.response.content
                try:
                    round_data["candidate_json"] = json.loads(candidate)
                except (TypeError, ValueError) as exc:
                    round_data["candidate_json_error_type"] = type(exc).__name__
                round_data["citation_differences"] = core._short_report_citation_diff(candidate, session.trace)
                round_data["outcome_root_cause_differences"] = core._short_report_field_diff(
                    candidate, session.trace)
                try:
                    validate_report(core._resolve_report_references(candidate, session.trace), session.trace)
                except (ValidationError, ValueError) as exc:
                    round_data["validation_error_type"] = type(exc).__name__
                    round_data["validation_error"] = str(exc)
                evidence.save()
                try:
                    route = await graph._validate_report({"session": session})
                except core.CoreAgentError:
                    round_data["status"] = "rejected"
                    raise
                if route["next_step"] == "end":
                    report = session.result.report
                    if (set(report.get("knowledge_source_ids", []))
                            != set(contract["knowledge_source_ids"])
                            or not all(f"{section}. " in session.result.answer
                                       for section in range(1, 7))):
                        round_data["status"] = "scenario_acceptance_failed"
                        evidence.data["error_code"] = "required_sop_or_handoff_missing"
                        break
                    round_data["status"] = "validated"
                    evidence.data.update(
                        result_class="first_answer_pass" if index == 1 else "corrected_pass",
                        report=report, rendered_report=session.result.answer,
                        rejected_finals=session.rejected,
                    )
                    break
                round_data["status"] = "rejected"
                round_data["feedback"] = session.messages[-1].content
                evidence.save()
                evidence.emit("report_rejected", index=index)
        if evidence.data["result_class"] is None:
            evidence.data["result_class"] = "final_failure"
    except Exception as exc:  # noqa: BLE001 -- preserve the only real attempt
        evidence.data.update(result_class="final_failure",
                             error_code=getattr(exc, "error_code", None) or
                             ("stage_timeout" if isinstance(exc, TimeoutError) else "report_stage_error"),
                             exception_chain_types=exception_types(exc),
                             rejected_finals=session.rejected)
    finally:
        evidence.data.update(status="finished", finished_at=datetime.now(UTC).isoformat(),
                             elapsed_seconds=round(time.perf_counter() - started, 3),
                             model_calls=len(evidence.data["rounds"]))
        await inner._client.aclose()
        evidence.save()
        evidence.emit("attempt_finished", result_class=evidence.data["result_class"],
                      error_code=evidence.data.get("error_code"))
        evidence.active.unlink()
    print(json.dumps({key: evidence.data.get(key) for key in
                      ("result_class", "error_code", "model_calls", "elapsed_seconds")}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("check", "run"))
    args = parser.parse_args()
    if args.mode == "check":
        saved, _, contract = prepare()
        print(json.dumps({"source_request_id": saved["request_id"], "model": settings.LLM_MODEL,
                          "http_timeout": settings.LLM_REQUEST_TIMEOUT_SECONDS,
                          "model_deadline": core.MODEL_TIMEOUT_SECONDS,
                          "max_tokens": settings.LLM_MAX_TOKENS,
                          "observations": len(saved["trace"]),
                          "event_refs": len(contract["evidence_event_ids"]),
                          "knowledge_refs": len(contract["knowledge_source_ids"]),
                          "root_cause": contract["root_cause"]}))
    else:
        asyncio.run(run())


if __name__ == "__main__":
    main()
