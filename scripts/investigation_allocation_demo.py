"""Isolated, one-browser-submit allocation investigation demo.

Creates only allocation_demo_* in ragforge_day6_test and a private Qdrant
collection. Existing action/request and investigation demo data are read only.
"""

import argparse
import asyncio
import importlib.util
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import action_request_demo as demo  # Pins the isolated DB before app imports.
import httpx
import investigation_page_demo as previous  # Reuse observation without altering it.
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.ai.agents import core_agent as core
from app.ai.agents import core_graph
from app.ai.agents.core_agent import CoreAgentError
from app.ai.agents.investigation_report import validate_report
from app.ai.embeddings.factory import get_embedding_provider
from app.ai.vectorstore.factory import get_vector_store
from app.api.v1.endpoints import investigations
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.redis_client import get_redis_client
from app.db.base import Base
from app.db.session import get_db
from app.middleware.request_context import RequestContextMiddleware
from app.models.exception_case import ExceptionCase
from app.models.fulfillment_event import FulfillmentEvent
from app.models.order import Order
from app.models.organization import Organization, OrganizationMember
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.services import fulfillment_service
from fastapi import FastAPI
from knowledge_retrieval_verify import index_samples, seed_reference
from langchain_core.tools import StructuredTool
from qdrant_client import AsyncQdrantClient
from sqlalchemy import MetaData, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.contextvars import get_contextvars

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "scripts/investigation_allocation_demo_state.json"
LATEST = ROOT / "scripts/investigation_allocation_latest.json"
PREFIX = "allocation_demo_"
COLLECTION_PREFIX = "project_a_knowledge_test_"
QUESTION = (
    "核查本订单对应运单的发货延迟：读取订单级库存分配失败和明确的延迟关联记录，"
    "区分已记录的分配受阻与延迟归因；查阅授权的订单履约调查 SOP，分别引用业务事件与规则来源。"
    "不要将该运单结论扩大为整单或唯一根因；建议尚未执行。"
)
SOP_NAME = "Order-allocation-review-SOP.txt"
SOP_TEXT = (
    "订单履约调查 SOP：核对订单、同一运单的承诺与实际发货时间、库存分配失败的来源记录，"
    "以及明确引用该失败事件的发货延迟关联记录。仅有库存快照或分配失败记录不能确定延迟原因。"
    "建议人工核对分配系统与履约系统记录；本规则不是订单业务事实，不证明客户已收到通知或建议已执行。"
)
TABLES = (
    "organizations", "users", "organization_members", "refresh_tokens",
    "workspaces", "workspace_members", "documents", "document_chunks",
)


def save(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def state_read() -> dict:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if (state["database"] != "ragforge_day6_test"
            or not state["schema"].startswith(PREFIX)
            or len(state["schema"]) != len(PREFIX) + 32
            or not state["collection"].startswith(COLLECTION_PREFIX)
            or len(state["collection"]) != len(COLLECTION_PREFIX) + 32):
        raise RuntimeError("Allocation fixture identity is invalid")
    UUID(hex=state["schema"].removeprefix(PREFIX))
    UUID(hex=state["collection"].removeprefix(COLLECTION_PREFIX))
    return state


def configure(state: dict) -> None:
    previous.configure(state["collection"])
    if settings.LLM_PROVIDER != "ollama":
        raise RuntimeError("Expected existing local Ollama chat provider")


def apply_migrations(sync) -> None:
    metadata = MetaData()
    for name in TABLES:
        Base.metadata.tables[name].to_metadata(metadata)
    metadata.create_all(sync)
    with Operations.context(MigrationContext.configure(sync)):
        for filename in (
            "0002_commerce_core.py", "0003_fulfillment_investigation.py",
            "0008_order_allocation_evidence.py",
        ):
            path = ROOT / "backend/alembic/versions" / filename
            spec = importlib.util.spec_from_file_location(filename, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.upgrade()


async def preflight() -> None:
    previous.configure(COLLECTION_PREFIX + uuid4().hex)  # Process-local; no collection is created.
    retained = demo.load_state()
    base, source = demo.engines(retained["schema"])
    try:
        async with base.connect() as conn:
            await demo.assert_database(conn)
        async with source.connect() as conn:
            if await conn.scalar(text("SELECT current_schema()")) != retained["schema"]:
                raise RuntimeError("Retained identity schema unavailable")
            if not await conn.scalar(select(User.id).where(User.id == UUID(retained["member_id"]))):
                raise RuntimeError("Retained member is unavailable")
    finally:
        await source.dispose()
        await base.dispose()
    redis = get_redis_client()
    try:
        if not await redis.ping():
            raise RuntimeError("Redis PING failed")
    finally:
        await redis.aclose()
        get_redis_client.cache_clear()
    client = AsyncQdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)
    try:
        await client.get_collections()
    finally:
        await client.close()
    async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL, timeout=8) as http:
        for model in ("llama3.1:8b", settings.EMBEDDING_MODEL):
            response = await http.post("/api/show", json={"model": model})
            response.raise_for_status()
    print(json.dumps({"pg": "ragforge_day6_test", "redis": "PONG",
                      "qdrant": "ok", "ollama_models": "metadata_available"}))


async def prepare() -> None:
    if STATE.exists():
        raise RuntimeError("Allocation fixture already exists; inspect it")
    retained = demo.load_state()
    now = datetime.now(UTC)
    event_ids = [str(uuid4()) for _ in range(6)]
    state = {
        "database": "ragforge_day6_test", "schema": PREFIX + uuid4().hex,
        "collection": COLLECTION_PREFIX + uuid4().hex,
        "organization_id": retained["organization_id"], "user_id": retained["member_id"],
        "login_state": str(demo.STATE.relative_to(ROOT)),
        "case_id": str(uuid4()), "order_id": str(uuid4()), "workspace_id": str(uuid4()),
        "tracking_number": "ALLOCATION-DEMO-" + uuid4().hex[:10],
        "event_ids": event_ids, "as_of": now.isoformat(),
        "prepared": False, "schema_owned": False, "collection_owned": False,
    }
    configure(state)
    base, scoped = demo.engines(state["schema"])
    _, source = demo.engines(retained["schema"])
    store = embedding = None
    save(STATE, state)
    try:
        async with source.connect() as conn:
            if await conn.scalar(text("SELECT current_schema()")) != retained["schema"]:
                raise RuntimeError("Retained identity schema unavailable")
            org = (await conn.execute(select(Organization.__table__).where(
                Organization.id == UUID(retained["organization_id"])))).mappings().one()
            user = (await conn.execute(select(User.__table__).where(
                User.id == UUID(retained["member_id"])))).mappings().one()
            member = (await conn.execute(select(OrganizationMember.__table__).where(
                OrganizationMember.organization_id == org["id"],
                OrganizationMember.user_id == user["id"]))).mappings().one()
        async with base.begin() as conn:
            await demo.assert_database(conn)
            await conn.execute(text(f'CREATE SCHEMA "{state["schema"]}"'))
        state["schema_owned"] = True
        save(STATE, state)
        async with scoped.begin() as conn:
            await demo.assert_database(conn)
            if await conn.scalar(text("SELECT current_schema()")) != state["schema"]:
                raise RuntimeError("Wrong allocation schema")
            await conn.run_sync(apply_migrations)
            for table, row in ((Organization.__table__, org), (User.__table__, user),
                               (OrganizationMember.__table__, member)):
                await conn.execute(insert(table).values(**dict(row)))
            order_id, case_id = UUID(state["order_id"]), UUID(state["case_id"])
            await conn.execute(insert(Order).values(
                id=order_id, organization_id=org["id"], platform="synthetic_demo",
                store_key="allocation_browser", order_number="ALLOC-" + order_id.hex[:8],
                currency="USD", subtotal_amount=10, total_amount=10,
                ordered_at=now - timedelta(days=1)))
            await conn.execute(insert(ExceptionCase).values(
                id=case_id, organization_id=org["id"], order_id=order_id,
                exception_type="shipment_delay", problem_description=QUESTION,
                opened_at=now - timedelta(hours=7)))
            tracking = state["tracking_number"]
            rows = (
                ("shipment_promised", -6, -4, "fulfillment-demo", None, None,
                 "该运单承诺发货截止时间。"),
                ("delivery_promised", -6, -1, "fulfillment-demo", None, None,
                 "该运单承诺送达截止时间。"),
                ("inventory_allocation_failed", -5, None, "allocation-demo", "allocation-failed-1", None,
                 "该订单、该运单的库存分配失败记录；不单独证明延迟原因。"),
                ("shipment_delay_attributed", -3.5, None, "allocation-demo", "delay-linked-1",
                 event_ids[2], "来源记录明确将本运单发货延迟关联到该次分配失败。"),
                ("shipped", -3, None, "fulfillment-demo", None, None, "实际发货时间。"),
                ("delivered", -2, None, "fulfillment-demo", None, None, "实际送达时间。"),
            )
            for identifier, (kind, hours, expected, source_name, external, related, description) in zip(
                event_ids, rows, strict=True,
            ):
                await conn.execute(insert(FulfillmentEvent).values(
                    id=UUID(identifier), organization_id=org["id"], order_id=order_id,
                    event_type=kind, occurred_at=now + timedelta(hours=hours),
                    expected_at=now + timedelta(hours=expected) if expected is not None else None,
                    source=source_name, external_event_id=external,
                    caused_by_event_id=UUID(related) if related else None,
                    tracking_number=tracking, description=description))
            workspace_id = UUID(state["workspace_id"])
            await conn.execute(insert(Base.metadata.tables["workspaces"]).values(
                id=workspace_id, organization_id=org["id"],
                name="订单库存分配调查 SOP 演示", slug="allocation-" + workspace_id.hex))
            await conn.execute(insert(WorkspaceMember).values(
                id=uuid4(), workspace_id=workspace_id, user_id=user["id"], role="viewer"))
            state["sample"] = await seed_reference(
                conn, workspace=workspace_id, user=user["id"], filename=SOP_NAME, content=SOP_TEXT)
        save(STATE, state)
        store, embedding = get_vector_store(), get_embedding_provider()
        if await store._client.collection_exists(state["collection"]):
            raise RuntimeError("Private collection already exists")
        await store.ensure_collection()
        state["collection_owned"] = True
        save(STATE, state)
        if await index_samples(embedding, store, [state["sample"]]) != [state["sample"]["chunk_id"]]:
            raise RuntimeError("SOP indexing did not match its database chunk")
        state["prepared"] = True
        save(STATE, state)
        print(json.dumps({key: state[key] for key in (
            "database", "schema", "case_id", "workspace_id", "collection", "as_of", "prepared",
        )}))
    finally:
        if store is not None:
            await store._client.close()
        if embedding is not None:
            await embedding._client.aclose()
        await source.dispose()
        await scoped.dispose()
        await base.dispose()


async def inspect() -> None:
    state = state_read()
    configure(state)
    _, scoped = demo.engines(state["schema"])
    try:
        async with AsyncSession(scoped, expire_on_commit=False) as db:
            await demo.assert_database(await db.connection())
            result = await fulfillment_service.analyze_fulfillment(
                db, organization_id=UUID(state["organization_id"]),
                order_id=UUID(state["order_id"]), as_of=datetime.fromisoformat(state["as_of"]),
            )
            if (result["shipment"]["status"] != "late"
                    or result["allocation"]["causal_status"] != "linked_to_shipment_delay"
                    or set(result["evidence_event_ids"]) != {UUID(value) for value in state["event_ids"]}):
                raise RuntimeError("Synthetic order evidence is incomplete")
        client = AsyncQdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)
        try:
            collection_exists = await client.collection_exists(state["collection"])
        finally:
            await client.close()
        if not collection_exists:
            raise RuntimeError("Private SOP collection is absent")
        print(json.dumps({"database": state["database"], "schema": state["schema"],
                          "case_id": state["case_id"], "workspace_id": state["workspace_id"],
                          "as_of": state["as_of"], "events": len(state["event_ids"]),
                          "allocation": "linked_to_shipment_delay", "collection_exists": True}))
    finally:
        await scoped.dispose()


class RunEvidence:
    def __init__(self, request_id: str, state: dict, kwargs: dict):
        stem = ROOT / "scripts" / ("investigation_allocation_run_"
                                   + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                                   + "_" + uuid4().hex[:8])
        self.snapshot, self.events = stem.with_suffix(".json"), stem.with_suffix(".jsonl")
        self.phase = "investigation"
        self.model_index = 0
        self.data = {
            "request_id": request_id, "case_id": state["case_id"],
            "organization_id": str(kwargs["organization_id"]),
            "workspace_id": str(kwargs.get("workspace_id")),
            "require_knowledge": kwargs.get("require_knowledge", False),
            "as_of": kwargs["as_of"].isoformat(), "graph": "core_graph.run_graph",
            "started_at": datetime.now(UTC).isoformat(), "passed": False,
            "trace": [], "rejections": [], "model_timings": [], "tool_timings": [],
            "phase_changes": [], "events_path": str(self.events.relative_to(ROOT)),
        }
        save(self.snapshot, self.data)
        save(LATEST, {"snapshot": str(self.snapshot.relative_to(ROOT)),
                      "events": str(self.events.relative_to(ROOT)), "request_id": request_id})
        self.emit("request_started")

    def emit(self, name: str, **values) -> None:
        row = {"at": datetime.now(UTC).isoformat(), "event": name, **values}
        with self.events.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if name == "tool_observed":
            self.data["trace"].append(values["step"])
        elif name == "report_rejected":
            self.data["rejections"].append(values)
        elif name in ("model_completed", "model_cancelled"):
            self.data["model_timings"].append(values)
        elif name == "tool_completed":
            self.data["tool_timings"].append(values)
        elif name == "phase_changed":
            self.phase = "report" if values["final_only"] else "investigation"
            self.data["phase_changes"].append(values)
        elif name == "http_response":
            self.data["http_status"] = values["status"]
        save(self.snapshot, self.data)


class TimedProvider:
    def __init__(self, inner, sink: RunEvidence):
        self.inner, self.sink = inner, sink

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def generate_with_tools(self, *args, **kwargs):
        self.sink.model_index += 1
        index, phase = self.sink.model_index, self.sink.phase
        started = time.monotonic()
        try:
            response = await self.inner.generate_with_tools(*args, **kwargs)
        except asyncio.CancelledError:
            self.sink.emit("model_cancelled", index=index, phase=phase,
                           elapsed_seconds=round(time.monotonic() - started, 3),
                           exception_type="CancelledError")
            raise
        except Exception as exc:
            self.sink.emit("model_completed", index=index, phase=phase,
                           elapsed_seconds=round(time.monotonic() - started, 3),
                           exception_type=type(exc).__name__)
            raise
        self.sink.emit("model_completed", index=index, phase=phase,
                       elapsed_seconds=round(time.monotonic() - started, 3),
                       stop_reason=response.stop_reason,
                       input_tokens=response.usage.input_tokens,
                       output_tokens=response.usage.output_tokens,
                       server_timing_ns=response.server_timing_ns,
                       **({"raw_candidate": response.content,
                           "candidate_json": _candidate_json(response.content),
                           "citation_differences": (
                               core._short_report_citation_diff(response.content, self.sink.data["trace"])
                               if core.SHORT_REPORT_BOUNDARY in kwargs.get("system", "") else
                               core._report_citation_diff(response.content, self.sink.data["trace"]))}
                          if phase == "report" else {}))
        return response


def _candidate_json(content: str):
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return None


def serve() -> None:
    import uvicorn

    state = state_read()
    if not state["prepared"]:
        raise RuntimeError("Allocation fixture is not ready")
    configure(state)
    _, scoped = demo.engines(state["schema"])
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(demo.api_router, prefix="/api/v1")

    async def isolated_db():
        async with AsyncSession(scoped, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    original_graph = investigations.run_core_agent
    original_tool = StructuredTool.ainvoke
    core_graph.CoreSession = previous.ObservedCoreSession
    runs: dict[str, RunEvidence] = {}

    async def timed_tool(tool, *args, **kwargs):
        sink = previous.ACTIVE_EVIDENCE.get()
        started = time.monotonic()
        try:
            result = await original_tool(tool, *args, **kwargs)
        except Exception as exc:
            if sink:
                sink.emit("tool_completed", tool=tool.name,
                          elapsed_seconds=round(time.monotonic() - started, 3),
                          exception_type=type(exc).__name__)
            raise
        if sink:
            sink.emit("tool_completed", tool=tool.name,
                      elapsed_seconds=round(time.monotonic() - started, 3),
                      status=result.get("status") if isinstance(result, dict) else None)
        return result

    StructuredTool.ainvoke = timed_tool

    async def observed_graph(provider, db, **kwargs):
        if (str(kwargs["case_id"]) != state["case_id"]
                or str(kwargs["organization_id"]) != state["organization_id"]):
            return await original_graph(provider, db, **kwargs)
        request_id = get_contextvars().get("request_id")
        if not request_id:
            raise RuntimeError("Request ID missing before investigation")
        sink = RunEvidence(request_id, state, kwargs)
        runs[request_id] = sink
        token = previous.ACTIVE_EVIDENCE.set(sink)
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(original_graph(TimedProvider(provider, sink), db, **kwargs),
                                            timeout=690)
            sink.data.update(passed=True, trace=result.trace, report=result.report,
                             handoff=result.answer, model_requests=result.model_requests,
                             rejected_finals=result.rejected_finals)
            return result
        except CoreAgentError as exc:
            sink.data.update(error_code=exc.error_code, trace=exc.trace,
                             model_requests=exc.model_requests,
                             rejected_finals=getattr(exc, "rejected_finals", []))
            raise
        except TimeoutError:
            sink.data["error_code"] = "outer_timeout"
            raise
        except asyncio.CancelledError:
            sink.data["error_code"] = "request_cancelled"
            raise
        except Exception as exc:
            sink.data.update(error_code="unhandled_exception", exception_type=type(exc).__name__)
            raise
        finally:
            previous.ACTIVE_EVIDENCE.reset(token)
            sink.data["elapsed_seconds"] = round(time.monotonic() - started, 3)
            sink.data["finished_at"] = datetime.now(UTC).isoformat()
            save(sink.snapshot, sink.data)
            sink.emit("request_finished", passed=sink.data["passed"],
                      error_code=sink.data.get("error_code"),
                      elapsed_seconds=sink.data["elapsed_seconds"])

    investigations.run_core_agent = observed_graph

    async def recorded_http(scope, receive, send):
        if scope["type"] != "http" or not scope["path"].endswith("/investigations"):
            return await app(scope, receive, send)

        async def recorded_send(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                request_id = headers.get(b"x-request-id", b"").decode("ascii", errors="replace")
                sink = runs.get(request_id)
                if sink is not None:
                    sink.emit("http_response", status=message["status"])
                    runs.pop(request_id, None)
            await send(message)

        await app(scope, receive, recorded_send)

    uvicorn.run(recorded_http, host="127.0.0.1", port=8125, log_level="warning")


def verify() -> None:
    state = state_read()
    latest = json.loads(LATEST.read_text(encoding="utf-8"))
    evidence_path = ROOT / latest["snapshot"]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    trace, report = evidence.get("trace", []), evidence.get("report")
    handoff = evidence.get("handoff") or ""
    path = [step["tool"] for step in trace if step["result"]["status"] != "invalid_input"]
    checks = {
        "request_completed": evidence.get("passed") is True and evidence.get("http_status") == 200,
        "scoped_request": evidence.get("case_id") == state["case_id"]
        and evidence.get("organization_id") == state["organization_id"]
        and evidence.get("workspace_id") == state["workspace_id"]
        and evidence.get("require_knowledge") is True,
        "graph_business_knowledge_path": path[:2] == ["get_exception_case", "analyze_fulfillment"]
        and "search_knowledge" in path[2:],
        "knowledge_found": any(step["tool"] == "search_knowledge"
                               and step["result"]["status"] == "found"
                               and any(source["chunk_id"] == state["sample"]["chunk_id"]
                                       for source in step["result"]["sources"])
                               for step in trace),
        "report_phase_entered": any(change.get("final_only") is True
                                    for change in evidence.get("phase_changes", [])),
        "timings_recorded": len(evidence.get("model_timings", [])) == evidence.get("model_requests")
        and len(evidence.get("tool_timings", [])) >= len(path),
        "order_allocation_link": any(step["tool"] == "analyze_fulfillment"
                                     and step["result"]["status"] == "found"
                                     and step["result"]["analysis"].get("allocation", {}).get("causal_status")
                                     == "linked_to_shipment_delay" for step in trace),
        "outcome_and_limited_cause": isinstance(report, dict)
        and report.get("outcome") == "observed_delay"
        and report.get("root_cause") == "inventory_allocation_blocked",
        "six_event_citations": isinstance(report, dict)
        and set(report.get("evidence_event_ids", [])) == set(state["event_ids"]),
        "separate_sop_citation_if_used": isinstance(report, dict)
        and set(report.get("knowledge_source_ids", [])) <= {state["sample"]["chunk_id"]}
        and state["sample"]["chunk_id"] not in report.get("evidence_event_ids", []),
        "six_part_handoff": all(heading in handoff for heading in (
            "1. 已确认事实", "2. 证据引用及观察时间", "3. 不能确认的事项",
            "4. 缺少的资料", "5. 与资料缺口逐项对应的下一步建议", "6. 处理状态",
        )),
        "limited_wording": "该运单发货延迟" in handoff and "整单完成情况未知" in handoff
        and "未执行处置" in handoff,
    }
    try:
        validate_report(json.dumps(report), trace)
        checks["report_validator"] = True
    except (TypeError, ValueError):
        checks["report_validator"] = False
    result = {"passed": all(checks.values()), "checks": checks,
              "tool_path": path, "elapsed_seconds": evidence.get("elapsed_seconds"),
              "request_id": evidence.get("request_id"),
              "source_evidence": str(evidence_path.relative_to(ROOT))}
    output = ROOT / "scripts/investigation_allocation_run_acceptance_short_refs_20261021.json"
    save(output, result)
    print(json.dumps(result, ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


async def cleanup() -> None:
    state = state_read()
    configure(state)
    base, _ = demo.engines(state["schema"])
    try:
        async with base.begin() as conn:
            await demo.assert_database(conn)
            if state["schema_owned"]:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{state["schema"]}" CASCADE'))
        client = AsyncQdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)
        try:
            if state["collection_owned"] and await client.collection_exists(state["collection"]):
                await client.delete_collection(collection_name=state["collection"])
        finally:
            await client.close()
        STATE.unlink()
    finally:
        await base.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "prepare", "inspect", "serve", "verify", "cleanup"))
    command = parser.parse_args().command
    if command == "serve":
        serve()
    elif command == "verify":
        verify()
    else:
        asyncio.run({"preflight": preflight, "prepare": prepare,
                     "inspect": inspect, "cleanup": cleanup}[command]())
