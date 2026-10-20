"""Retained isolated browser fixture; no chat request during preparation.

Only ragforge_day6_test and the existing disposable action demo schema are used.
"""
import argparse
import asyncio
import json
import os
import time
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import action_request_demo as demo  # Pins the test DATABASE_URL before app imports.
from app.ai.agents import core_graph
from app.ai.agents.core_agent import CoreAgentError
from app.ai.agents.investigation_report import validate_report
from app.ai.embeddings.factory import get_embedding_provider
from app.ai.vectorstore.factory import get_vector_store
from app.api.v1.endpoints import investigations
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.db.base import Base
from app.db.session import get_db
from app.middleware.request_context import RequestContextMiddleware
from app.models.exception_case import ExceptionCase
from app.models.fulfillment_event import FulfillmentEvent
from app.models.order import Order
from app.models.workspace import WorkspaceMember
from fastapi import FastAPI
from investigation_c05 import QUESTION, SOP_NAME, SOP_TEXT
from knowledge_retrieval_verify import index_samples, seed_reference
from qdrant_client import AsyncQdrantClient
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.contextvars import get_contextvars

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "scripts/investigation_page_demo_state.json"
EVIDENCE = ROOT / "scripts/investigation_page_graph_evidence.json"
LATEST = ROOT / "scripts/investigation_page_latest.json"
PREFIX = "project_a_knowledge_test_"
TABLES = ("fulfillment_events", "workspaces", "workspace_members", "documents", "document_chunks")
ACTIVE_EVIDENCE: ContextVar["RunEvidence | None"] = ContextVar("investigation_page_evidence", default=None)


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


class RunEvidence:
    """Per-request snapshot plus fsynced events; never overwrite an earlier run."""

    def __init__(self, request_id: str, state: dict, kwargs: dict):
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        stem = ROOT / "scripts" / f"investigation_page_run_{stamp}_{uuid4().hex[:8]}"
        self.snapshot = stem.with_suffix(".json")
        self.events = stem.with_suffix(".jsonl")
        self.data = {
            "request_id": request_id, "case_id": state["case_id"],
            "organization_id": str(kwargs["organization_id"]),
            "workspace_id": str(kwargs.get("workspace_id")),
            "require_knowledge": kwargs.get("require_knowledge", False),
            "graph_entry": "app.ai.agents.core_agent.run_core_agent -> core_graph.run_graph",
            "started_at": datetime.now(UTC).isoformat(), "passed": False,
            "trace": [], "rejections": [], "events_path": str(self.events.relative_to(ROOT)),
        }
        save(self.snapshot, self.data)
        save(LATEST, {"snapshot": str(self.snapshot.relative_to(ROOT)),
                      "events": str(self.events.relative_to(ROOT)), "request_id": request_id})
        self.emit("request_started")

    def emit(self, name: str, **values):
        row = {"at": datetime.now(UTC).isoformat(), "event": name, **values}
        with self.events.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if name == "tool_observed":
            self.data["trace"].append(values["step"])
        elif name == "report_rejected":
            self.data["rejections"].append(values)
        elif name == "http_response":
            self.data["http_status"] = values["status"]
        save(self.snapshot, self.data)


class ObservedList(list):
    def __init__(self, items, sink: RunEvidence, name: str):
        super().__init__(items)
        self.sink, self.name = sink, name

    def append(self, item):
        super().append(item)
        if self.name == "trace":
            self.sink.emit("tool_observed", step=item)
        else:
            self.sink.emit("report_rejected", reason=item.get("reason"),
                           phase=item.get("phase"))


class ObservedCoreSession(core_graph.CoreSession):
    """Observe existing Graph state transitions without changing nodes or edges."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        sink = ACTIVE_EVIDENCE.get()
        if sink is not None:
            self.trace = ObservedList(self.trace, sink, "trace")
            self.rejected = ObservedList(self.rejected, sink, "rejected")
        self._evidence_sink = sink

    def __setattr__(self, name, value):
        previous = self.__dict__.get(name)
        super().__setattr__(name, value)
        sink = self.__dict__.get("_evidence_sink")
        if sink is None:
            return
        if name == "final_only" and previous is not None and previous != value:
            sink.emit("phase_changed", final_only=value)
        elif name == "requests" and isinstance(previous, int) and value > previous:
            sink.emit("model_request_started", index=value,
                      phase="report" if self.final_only else "investigation")
        elif name == "response" and value is not None and value is not previous:
            sink.emit("model_response", index=self.requests,
                      stop_reason=value.stop_reason,
                      tool_calls=[call.name for call in value.tool_calls],
                      content_chars=len(value.content))


def state_read():
    state = json.loads(STATE.read_text(encoding="utf-8"))
    retained = demo.load_state()
    if (state["database"] != "ragforge_day6_test" or
        state["schema"] != retained["schema"] or
        state["organization_id"] != retained["organization_id"] or
        not state["collection"].startswith(PREFIX) or
        len(state["collection"]) != len(PREFIX) + 32):
        raise RuntimeError("Investigation fixture does not match retained test demo")
    UUID(hex=state["collection"].removeprefix(PREFIX))
    return state


def configure(collection):
    settings.QDRANT_COLLECTION_NAME = collection
    parsed = urlsplit(settings.REDIS_URL)
    auth = parsed.netloc.rpartition("@")[0] + "@" if "@" in parsed.netloc else ""
    settings.REDIS_URL = urlunsplit(parsed._replace(netloc=auth + "localhost:6380"))
    settings.LLM_PROVIDER = "ollama"
    settings.LLM_MODEL = "llama3.1:8b"
    settings.LLM_MAX_TOKENS = 700
    settings.LLM_REQUEST_TIMEOUT_SECONDS = 190
    if settings.EMBEDDING_PROVIDER != "ollama" or settings.EMBEDDING_DIMENSIONS != 768:
        raise RuntimeError("Embedding configuration differs from existing C05 fixture")


async def prepare():
    if STATE.exists():
        raise RuntimeError("Investigation fixture already exists; inspect it")
    retained = demo.load_state()
    schema = retained["schema"]
    state = {
        "database": "ragforge_day6_test", "schema": schema,
        "organization_id": retained["organization_id"], "user_id": retained["member_id"],
        "collection": PREFIX + uuid4().hex, "case_id": str(uuid4()),
        "order_id": str(uuid4()), "workspace_id": str(uuid4()),
        "event_ids": [str(uuid4()) for _ in range(4)], "prepared": False,
    }
    configure(state["collection"])
    base, scoped = demo.engines(schema)
    store = embedding = None
    try:
        async with base.connect() as conn:
            await demo.assert_database(conn)
        store, embedding = get_vector_store(), get_embedding_provider()
        if await store._client.collection_exists(state["collection"]):
            raise RuntimeError("Dedicated collection already exists")
        async with scoped.begin() as conn:
            await demo.assert_database(conn)
            if await conn.scalar(text("SELECT current_schema()")) != schema:
                raise RuntimeError("Wrong test schema")
            for name in TABLES:
                await conn.run_sync(lambda sync, name=name: Base.metadata.tables[name].create(sync, checkfirst=True))
            org, order = UUID(state["organization_id"]), UUID(state["order_id"])
            now = datetime.now(UTC)
            await conn.execute(insert(Order).values(
                id=order, organization_id=org, platform="isolated_demo",
                store_key="graph_browser", order_number="GRAPH-" + order.hex[:8],
                currency="USD", subtotal_amount=10, total_amount=10,
                ordered_at=now - timedelta(days=1)))
            await conn.execute(insert(ExceptionCase).values(
                id=UUID(state["case_id"]), organization_id=org, order_id=order,
                exception_type="other", problem_description=QUESTION,
                opened_at=now - timedelta(hours=7)))
            for identifier, kind, hours, deadline in zip(
                state["event_ids"],
                ("shipment_promised", "delivery_promised", "shipped", "delivered"),
                (-6, -6, -3, -2), (-4, -1, None, None), strict=True,
            ):
                await conn.execute(insert(FulfillmentEvent).values(
                    id=UUID(identifier), organization_id=org, order_id=order,
                    event_type=kind, occurred_at=now + timedelta(hours=hours),
                    expected_at=now + timedelta(hours=deadline) if deadline is not None else None,
                    source="isolated_demo", tracking_number="GRAPH-BROWSER-SHIPMENT",
                    description="Recorded fulfillment timing; cause unconfirmed."))
            workspace, user = UUID(state["workspace_id"]), UUID(state["user_id"])
            await conn.execute(insert(Base.metadata.tables["workspaces"]).values(
                id=workspace, organization_id=org, name="订单履约调查 SOP 演示",
                slug="graph-browser-" + workspace.hex))
            await conn.execute(insert(WorkspaceMember).values(
                id=uuid4(), workspace_id=workspace, user_id=user, role="viewer"))
            state["sample"] = await seed_reference(
                conn, workspace=workspace, user=user, filename=SOP_NAME, content=SOP_TEXT)
        save(STATE, state)  # Persist cleanup IDs before indexing.
        await store.ensure_collection()
        indexed = await index_samples(embedding, store, [state["sample"]])
        if indexed != [state["sample"]["chunk_id"]]:
            raise RuntimeError("SOP index does not match its database chunk")
        state["prepared"] = True
        save(STATE, state)
        print(json.dumps({key: state[key] for key in (
            "database", "schema", "organization_id", "case_id", "workspace_id",
            "collection", "event_ids", "prepared")}))
    finally:
        if store is not None:
            await store._client.close()
        if embedding is not None:
            await embedding._client.aclose()
        await scoped.dispose()
        await base.dispose()


async def inspect():
    state = state_read()
    _, scoped = demo.engines(state["schema"])
    try:
        async with scoped.connect() as conn:
            await demo.assert_database(conn)
            if await conn.scalar(text("SELECT current_schema()")) != state["schema"]:
                raise RuntimeError("Wrong test schema")
            rows = {}
            for table, identifier in (
                ("exception_cases", state["case_id"]), ("orders", state["order_id"]),
                ("workspaces", state["workspace_id"]),
                ("document_chunks", state["sample"]["chunk_id"]),
            ):
                rows[table] = bool(await conn.scalar(text(
                    f"SELECT EXISTS(SELECT 1 FROM {table} WHERE id=:id)"
                ), {"id": UUID(identifier)}))
            rows["fulfillment_events"] = int(await conn.scalar(text(
                "SELECT count(*) FROM fulfillment_events WHERE order_id=:id"
            ), {"id": UUID(state["order_id"])}))
        client = AsyncQdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)
        try:
            collection_exists = await client.collection_exists(state["collection"])
        finally:
            await client.close()
        print(json.dumps({"database": state["database"], "schema": state["schema"],
                          "case_id": state["case_id"], "workspace_id": state["workspace_id"],
                          "prepared": state["prepared"], "rows": rows,
                          "collection_exists": collection_exists}))
    finally:
        await scoped.dispose()


def serve():
    """Dedicated API; wrapper observes the original Graph and keeps original budgets."""
    import uvicorn

    state = state_read()
    if not state["prepared"]:
        raise RuntimeError("Fixture is not ready")
    configure(state["collection"])
    _, scoped = demo.engines(state["schema"])
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(demo.api_router, prefix="/api/v1")

    async def isolated_db():
        async with AsyncSession(scoped, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    original = investigations.run_core_agent
    core_graph.CoreSession = ObservedCoreSession
    runs: dict[str, RunEvidence] = {}

    async def observed_graph(provider, db, **kwargs):
        if str(kwargs["case_id"]) != state["case_id"]:
            return await original(provider, db, **kwargs)
        started = time.monotonic()
        request_id = get_contextvars().get("request_id")
        if not request_id:
            raise RuntimeError("Request ID missing before investigation")
        sink = RunEvidence(request_id, state, kwargs)
        runs[request_id] = sink
        token = ACTIVE_EVIDENCE.set(sink)
        try:
            result = await asyncio.wait_for(original(provider, db, **kwargs), timeout=690)
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
            ACTIVE_EVIDENCE.reset(token)
            sink.data["elapsed_seconds"] = round(time.monotonic() - started, 3)
            sink.data["finished_at"] = datetime.now(UTC).isoformat()
            save(sink.snapshot, sink.data)
            sink.emit("request_finished", passed=sink.data["passed"],
                      error_code=sink.data.get("error_code"),
                      elapsed_seconds=sink.data["elapsed_seconds"],
                      model_requests=sink.data.get("model_requests"),
                      report=sink.data.get("report"), handoff=sink.data.get("handoff"))

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

    uvicorn.run(recorded_http, host="127.0.0.1", port=8124, log_level="warning")


async def cleanup():
    state = state_read()
    if state["collection"] == settings.QDRANT_COLLECTION_NAME:
        raise RuntimeError("Refusing default collection")
    _, scoped = demo.engines(state["schema"])
    try:
        async with scoped.begin() as conn:
            await demo.assert_database(conn)
            if await conn.scalar(text("SELECT current_schema()")) != state["schema"]:
                raise RuntimeError("Wrong test schema")
            await conn.execute(text("DELETE FROM workspaces WHERE id=:id"),
                               {"id": UUID(state["workspace_id"])})
            await conn.execute(text("DELETE FROM fulfillment_events WHERE order_id=:id"),
                               {"id": UUID(state["order_id"])})
            await conn.execute(text("DELETE FROM exception_cases WHERE id=:id"),
                               {"id": UUID(state["case_id"])})
            await conn.execute(text("DELETE FROM orders WHERE id=:id"),
                               {"id": UUID(state["order_id"])})
        client = AsyncQdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)
        try:
            if await client.collection_exists(state["collection"]):
                await client.delete_collection(collection_name=state["collection"])
        finally:
            await client.close()
        STATE.unlink()
        print("Removed only this investigation fixture; action demo data retained")
    finally:
        await scoped.dispose()


def verify():
    """Evaluate the one browser-initiated report against its retained fixture."""
    state = state_read()
    if LATEST.exists():
        latest = json.loads(LATEST.read_text(encoding="utf-8"))
        evidence_path = ROOT / latest["snapshot"]
    else:
        evidence_path = EVIDENCE  # Historical run predates per-request evidence.
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    trace = evidence.get("trace", [])
    report = evidence.get("report")
    handoff = evidence.get("handoff", "")
    path = [step["tool"] for step in trace if step["result"]["status"] != "invalid_input"]
    checks = {
        "graph_response_recorded": evidence.get("passed") is True,
        "case_and_organization": evidence.get("case_id") == state["case_id"]
        and evidence.get("organization_id") == state["organization_id"],
        "authorized_sop_required": evidence.get("workspace_id") == state["workspace_id"]
        and evidence.get("require_knowledge") is True,
        "actual_tool_path": path == ["get_exception_case", "analyze_fulfillment", "search_knowledge"],
        "knowledge_found": any(step["tool"] == "search_knowledge"
                               and step["result"]["status"] == "found"
                               and any(source["chunk_id"] == state["sample"]["chunk_id"]
                                       for source in step["result"]["sources"])
                               for step in trace),
        "observed_delay_unknown": isinstance(report, dict)
        and report.get("outcome") == "observed_delay" and report.get("root_cause") == "unknown",
        "four_business_event_citations": isinstance(report, dict)
        and set(report.get("evidence_event_ids", [])) == set(state["event_ids"]),
        "separate_sop_citation": isinstance(report, dict)
        and report.get("knowledge_source_ids") == [state["sample"]["chunk_id"]]
        and state["sample"]["chunk_id"] not in report.get("evidence_event_ids", []),
        "six_part_handoff": all(heading in handoff for heading in (
            "1. 已确认事实", "2. 证据引用及观察时间", "3. 不能确认的事项",
            "4. 缺少的资料", "5. 与资料缺口逐项对应的下一步建议", "6. 处理状态")),
        "business_and_knowledge_visible": all(identifier in handoff for identifier in (
            *state["event_ids"], state["sample"]["chunk_id"],
            state["sample"]["document_id"], SOP_NAME)),
    }
    try:
        validate_report(json.dumps(report), trace)
        checks["report_validator"] = True
    except (TypeError, ValueError):
        checks["report_validator"] = False
    result = {"passed": all(checks.values()), "checks": checks,
              "elapsed_seconds": evidence.get("elapsed_seconds"), "tool_path": path,
              "source_evidence": str(evidence_path.relative_to(ROOT))}
    save(ROOT / "scripts/investigation_page_acceptance.json", result)
    print(json.dumps(result, ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "inspect", "serve", "verify", "cleanup"))
    command = parser.parse_args().command
    if command == "serve":
        serve()
    elif command == "verify":
        verify()
    else:
        asyncio.run({"prepare": prepare, "inspect": inspect, "cleanup": cleanup}[command]())
