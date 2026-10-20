"""D11-D13 real Ollama/PG matrix. Synthetic business records, real read chain.

C03/C04 reuse identical case/order/events and change only inventory quantities.
C08 deliberately causes an actual PostgreSQL statement timeout during a tool read.
No global pytest fixtures, business migrations, paid models or model-call mocks.
"""
import argparse
import asyncio
import json
import os
import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import FunctionType
from uuid import uuid4

# Reuse the audited fixed-test-DB bootstrap, without running its main function.
from day11_e2e import OBSERVED, ROOT, Day8PostgresTests, OllamaProvider, settings
from sqlalchemy import insert, text, update
from sqlalchemy.ext.asyncio import AsyncSession

# Keep bootstrap before app imports: it pins the isolated database and sys.path.
BOOTSTRAP_ROOT = ROOT

from app.ai.agents.core_agent import CoreAgentError, run_core_agent
from app.models.exception_case import ExceptionCase
from app.models.fulfillment_event import FulfillmentEvent
from app.models.inventory_record import InventoryRecord


async def seed(conn, org, order, helper, scenario):
    if scenario == "C07":
        return uuid4()
    case = helper.case(org, order)
    case["opened_at"] = OBSERVED - timedelta(hours=1)
    case["problem_description"] = (
        "Reservation/backorder review pending for SKU=Sku-A; investigate shipment timing. Cause unconfirmed."
        if scenario in ("C03", "C04") else "Investigate shipment timing. Cause unconfirmed."
    )
    await conn.execute(insert(ExceptionCase).values(**case))
    if scenario == "C06":
        return case["id"]
    rows = [
        helper.event(org, order, event_type="shipment_promised", tracking_number="SHIP-A",
                     occurred_at=OBSERVED - timedelta(hours=4), expected_at=OBSERVED - timedelta(hours=2),
                     description=("Reservation/backorder review pending for SKU=Sku-A; inventory availability unverified."
                                  if scenario in ("C03", "C04") else "Shipment promise recorded.")),
        helper.event(org, order, event_type="in_transit" if scenario in ("C03", "C04") else "shipped", tracking_number="SHIP-A",
                     occurred_at=OBSERVED - timedelta(hours=3 if scenario == "C01" else 1),
                     description="Warehouse note: picking and packing completed before handoff; no cause established."),
    ]
    if scenario == "C01":
        rows += [helper.event(org, order, event_type="delivery_promised", tracking_number="SHIP-A",
                              occurred_at=OBSERVED - timedelta(hours=4), expected_at=OBSERVED),
                 helper.event(org, order, event_type="delivered", tracking_number="SHIP-A",
                              occurred_at=OBSERVED - timedelta(minutes=30))]
    for row in rows:
        await conn.execute(insert(FulfillmentEvent).values(**row))
    if scenario in ("C03", "C04"):
        await conn.execute(insert(InventoryRecord).values(**Day8PostgresTests().record(
            org, on_hand_quantity=2 if scenario == "C03" else 10, reserved_quantity=5 if scenario == "C03" else 3,
        )))
    return case["id"]


class TimeoutSession(AsyncSession):
    async def execute(self, statement, *args, **kwargs):
        if "fulfillment_events" in str(statement):
            await super().execute(text("SET LOCAL statement_timeout = '20ms'"))
            await super().execute(text("SELECT pg_sleep(0.2)"))
        return await super().execute(statement, *args, **kwargs)


def model_exception_chain(exc):
    """Only structural diagnostics: never messages, source lines or locals."""
    chain = []
    seen = set()
    relation = "raised"
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        locations = []
        tb = exc.__traceback__
        while tb is not None:
            code = tb.tb_frame.f_code
            locations.append({
                "file": code.co_filename.replace("\\", "/").rsplit("/", 1)[-1],
                "function": code.co_name, "line": tb.tb_lineno,
            })
            tb = tb.tb_next
        codes = {}
        for name in ("errno", "winerror"):
            value = getattr(exc, name, None)
            if type(value) is int:
                codes[name] = value
        chain.append({"type": f"{type(exc).__module__}.{type(exc).__qualname__}",
                      "relation": relation, "codes": codes, "locations": locations})
        if exc.__cause__ is not None:
            exc, relation = exc.__cause__, "cause"
        elif not exc.__suppress_context__:
            exc, relation = exc.__context__, "context"
        else:
            break
    return chain


class EventLog:
    """Append only allowlisted metadata; each event survives process termination."""

    def __init__(self, path):
        self.path = path

    def emit(self, scenario, request, event, *, tool=None, status=None, elapsed=None, exc=None):
        names = {"get_exception_case", "analyze_fulfillment", "get_inventory_status",
                 "get_fulfillment_events"}
        statuses = {"found", "not_found", "invalid_input", "returned", "failed", "cancelled"}
        record = {"utc": datetime.now(UTC).isoformat(), "scenario": scenario,
                  "request": request, "event": event,
                  "tool": tool if tool in names else None,
                  "status": status if status in statuses else None,
                  "elapsed_seconds": elapsed,
                  "exception_chain": [item["type"] for item in model_exception_chain(exc)]}
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


class ObservedTool:
    def __init__(self, tool, events, scenario, request_number):
        self.tool, self.events = tool, events
        self.scenario, self.request_number = scenario, request_number

    def __getattr__(self, name):
        return getattr(self.tool, name)

    async def ainvoke(self, *args, **kwargs):
        request = self.request_number()
        started = time.monotonic()
        try:
            result = await self.tool.ainvoke(*args, **kwargs)
        except BaseException as exc:
            self.events.emit(self.scenario, request, "tool_failed", tool=self.tool.name,
                             status="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                             elapsed=round(time.monotonic() - started, 3), exc=exc)
            raise
        self.events.emit(self.scenario, request, "tool_returned", tool=self.tool.name,
                         status=result.get("status") if isinstance(result, dict) else "returned",
                         elapsed=round(time.monotonic() - started, 3))
        return result


def observed_agent(events, scenario, request_number):
    # A private globals mapping avoids mutating the shared Agent/tool factory.
    factory = run_core_agent.__globals__["create_investigation_tools"]

    def observed_factory(*args, **kwargs):
        return [ObservedTool(tool, events, scenario, request_number)
                for tool in factory(*args, **kwargs)]

    agent = FunctionType(run_core_agent.__code__,
                         {**run_core_agent.__globals__, "create_investigation_tools": observed_factory},
                         run_core_agent.__name__, run_core_agent.__defaults__, run_core_agent.__closure__)
    agent.__kwdefaults__ = run_core_agent.__kwdefaults__
    return agent


async def record_model_request(entry, call, *, events=None, scenario=None, **kwargs):
    entry["started_at_utc"] = datetime.now(UTC).isoformat()
    started = time.monotonic()
    if events is not None:
        events.emit(scenario, entry["request"], "model_started")
    try:
        response = await call(**kwargs)
    except BaseException as exc:
        # Failed requests retain metadata only, including when a caller prefilled content.
        request = entry["request"]
        started_at = entry["started_at_utc"]
        entry.clear()
        entry.update(request=request, started_at_utc=started_at,
                     failure_type=type(exc).__name__,
                     cause_type=type(exc.__cause__).__name__ if exc.__cause__ else None,
                     exception_chain=model_exception_chain(exc))
        if events is not None:
            events.emit(scenario, request, "model_failed",
                        status="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                        elapsed=round(time.monotonic() - started, 3), exc=exc)
        raise
    else:
        if events is not None:
            events.emit(scenario, entry["request"], "model_returned", status="returned",
                        elapsed=round(time.monotonic() - started, 3))
        return response
    finally:
        entry["ended_at_utc"] = datetime.now(UTC).isoformat()
        entry["elapsed_seconds"] = round(time.monotonic() - started, 3)


async def observe(conn, org, order, case_id, scenario, events):
    evidence = {"scenario": scenario, "case_id": str(case_id), "order_id": str(order),
                "model": "llama3.1:8b", "target": "localhost:5433/ragforge_day6_test",
                "status": "failed", "requests": [], "fault_injected": scenario == "C08"}

    class ObservedProvider(OllamaProvider):
        async def generate_with_tools(self, **kwargs):
            entry = {"request": len(evidence["requests"]) + 1,
                     "messages": [asdict(m) for m in kwargs["messages"]],
                     "offered_tools": [t.name for t in kwargs["tools"]], "system": kwargs["system"]}
            evidence["requests"].append(entry)
            print(f"{scenario}: real model request {entry['request']}", flush=True)
            response = await record_model_request(entry, super().generate_with_tools,
                                                  events=events, scenario=scenario, **kwargs)
            entry["response"] = asdict(response)
            print(json.dumps({"scenario": scenario, "calls": [c.name for c in response.tool_calls],
                              "final": response.content}, ensure_ascii=True), flush=True)
            return response

    provider = ObservedProvider()
    agent = observed_agent(events, scenario, lambda: len(evidence["requests"]))
    try:
        await conn.execute(text("SET LOCAL transaction_read_only = on"))
        session_type = TimeoutSession if scenario == "C08" else AsyncSession
        async with session_type(bind=conn, join_transaction_mode="create_savepoint") as db:
            try:
                result = await asyncio.wait_for(agent(
                    provider, db, organization_id=org, case_id=case_id, as_of=OBSERVED,
                ), timeout=600)
            except CoreAgentError as exc:
                evidence.update(error_code=exc.error_code, trace=exc.trace,
                                error_message=str(exc), model_requests=exc.model_requests,
                                rejected_finals=getattr(exc, "rejected_finals", []))
                if scenario == "C08" and exc.error_code == "tool_failed":
                    assert exc.trace[-1]["tool"] == "analyze_fulfillment"
                    assert exc.trace[-1]["result"]["status"] == "execution_failed"
                    assert evidence["requests"][-1]["response"]["tool_calls"][0]["name"] == "analyze_fulfillment", "No final generation after DB failure"
                    evidence["status"] = "passed_expected_failure"
                else:
                    raise
            else:
                evidence.update(asdict(result))
                path = [s["tool"] for s in result.trace if s["result"]["status"] != "invalid_input"]
                assert sum(s["result"]["status"] == "invalid_input" for s in result.trace) <= 1
                opening = ["get_exception_case", "analyze_fulfillment"]
                expected_paths = {
                    "C01": opening, "C02": opening, "C06": opening,
                    "C03": opening + ["get_inventory_status"],
                    "C04": opening + ["get_inventory_status", "get_fulfillment_events"],
                    "C07": ["get_exception_case"],
                }
                assert path == expected_paths[scenario], f"Unexpected path: {path}"
                expected_outcome = {"C01": "no_observed_delay", "C03": "insufficient_evidence",
                                    "C04": "insufficient_evidence", "C06": "insufficient_evidence",
                                    "C07": "not_found"}.get(scenario, "observed_delay")
                assert result.report["outcome"] == expected_outcome
                assert result.report["root_cause"] == "unknown"
                if scenario not in ("C06", "C07"):
                    assert result.report["evidence_event_ids"]
                    for identifier in result.report["evidence_event_ids"]:
                        assert identifier in result.answer
                if scenario == "C02":
                    assert '"difference_seconds": 3600.0' in result.answer
                    assert "2026-10-09T10:00:00+00:00" in result.answer
                if scenario in ("C03", "C04"):
                    inventory = next(s["result"]["inventory"] for s in result.trace if s["tool"] == "get_inventory_status")
                    assert inventory["available_quantity"] == (-3 if scenario == "C03" else 7)
                    assert inventory["observed_at"] in result.answer
                evidence["status"] = "passed"
    except Exception as exc:  # noqa: BLE001 -- preserve failure evidence and continue independent cases
        evidence["failure_type"] = type(exc).__name__
        if isinstance(exc, (CoreAgentError, AssertionError)):
            # These messages are our own safe contract/assertion diagnostics.
            # Never persist arbitrary DB/connection exception strings.
            evidence["error_message"] = str(exc)
        print(f"{scenario}: failed ({type(exc).__name__})", flush=True)
    finally:
        await provider._client.aclose()
    return evidence


async def main(cases):
    settings.LLM_MODEL = "llama3.1:8b"
    settings.OLLAMA_BASE_URL = "http://localhost:11434"
    settings.LLM_MAX_TOKENS = 700
    # Let the Agent's existing 180s bound own cancellation on local hardware.
    settings.LLM_REQUEST_TIMEOUT_SECONDS = 190
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "scripts" / f"day13_evidence_{stamp}.json"
    events = EventLog(output.with_suffix(".jsonl"))
    data = {"started_at": stamp, "cases": [], "counterfactual_pair_verified": False}

    def save():
        output.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    paired = [c for c in ("C03", "C04") if c in cases]
    groups = [[c] for c in cases if c not in paired] + ([paired] if paired else [])
    for group in groups:
        try:
            async with Day8PostgresTests().database("migration") as (conn, org, order, helper, _):
                case_id = await seed(conn, org, order, helper, group[0])
                for scenario in group:
                    if scenario == "C04" and "C03" in group:
                        await conn.execute(update(InventoryRecord).where(
                            InventoryRecord.organization_id == org, InventoryRecord.sku == "Sku-A",
                        ).values(on_hand_quantity=10, reserved_quantity=3))
                    phase = await conn.begin_nested()
                    try:
                        evidence = await observe(conn, org, order, case_id, scenario, events)
                    finally:
                        # Restores the prior transaction GUC; never switch a live
                        # read-only transaction to read-write via SET.
                        await phase.rollback()
                    data["cases"].append(evidence)
                    save()
            for item in data["cases"][-len(group):]:
                item["rollback_verified"] = True
        except Exception as exc:
            data["setup_or_cleanup_failure"] = type(exc).__name__
            save()
            raise
        save()
    pair = {item["scenario"]: item for item in data["cases"] if item["scenario"] in ("C03", "C04")}
    if len(pair) == 2 and all(item["status"] == "passed" for item in pair.values()):
        left, right = pair["C03"], pair["C04"]
        assert left["case_id"] == right["case_id"] and left["order_id"] == right["order_id"]
        left_found = [s["result"] for s in left["trace"] if s["result"]["status"] == "found"]
        right_found = [s["result"] for s in right["trace"] if s["result"]["status"] == "found"]
        assert left_found[:2] == right_found[:2], "Opening observations must be identical"
        data["counterfactual_pair_verified"] = True
    data["passed"] = all(item["status"].startswith("passed") for item in data["cases"])
    save()
    print(f"Evidence: {output}; passed={data['passed']}", flush=True)
    return 0 if data["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", nargs="+", choices=["C01", "C02", "C03", "C04", "C06", "C07", "C08"],
                        default=["C01", "C02", "C03", "C04", "C06", "C07", "C08"])
    raise SystemExit(asyncio.run(main(parser.parse_args().cases)))
