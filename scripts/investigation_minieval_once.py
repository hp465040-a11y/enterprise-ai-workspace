"""Local, single-attempt Graph/API evaluation against retained isolated fixtures.

`preflight` is read only. `run` reserves a unique local evidence marker before its
only model-triggering POST. Neither command creates or repairs business fixtures.
"""

import argparse
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import action_request_demo as demo  # Pins the isolated DB before app imports.
import httpx
import investigation_allocation_demo as allocation
import investigation_page_demo as page
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.ai.agents import core_graph
from app.ai.agents.core_agent import CoreAgentError
from app.ai.agents.investigation_report import render_report, validate_report
from app.api.v1.endpoints import investigations
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.db.session import get_db
from app.middleware.request_context import RequestContextMiddleware
from app.models.fulfillment_event import FulfillmentEvent
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langchain_core.tools import StructuredTool
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.contextvars import get_contextvars

ROOT = Path(__file__).resolve().parents[1]
ABSENT_CASE_ID = UUID("c0ffee00-0000-4000-8000-00000000c003")
B_AS_OF = "2026-10-19T15:01:09.364109+00:00"
B_SCHEMA = "action_demo_e023b320166644acb8429553ae39ad81"
EXPECTED = {
    "A": ("observed_delay", "inventory_allocation_blocked"),
    "B": ("observed_delay", "unknown"),
    "B2": ("observed_delay", "unknown"),
    "C": ("not_found", "unknown"),
}
EVENT_COLUMNS = {
    "id": ("uuid", "NO"), "organization_id": ("uuid", "NO"), "order_id": ("uuid", "NO"),
    "event_type": ("character varying", "NO"),
    "occurred_at": ("timestamp with time zone", "NO"),
    "expected_at": ("timestamp with time zone", "YES"),
    "source": ("character varying", "NO"),
    "external_event_id": ("character varying", "YES"),
    "tracking_number": ("character varying", "YES"),
    "description": ("text", "NO"),
    "created_at": ("timestamp with time zone", "NO"),
}
EVENT_BASE_CHECKS = {
    "ck_fulfillment_events_type", "ck_fulfillment_events_expected_at",
    "ck_fulfillment_events_source_nonempty",
    "ck_fulfillment_events_description_nonempty",
    "ck_fulfillment_events_external_id_nonempty",
}
EVENT_0008_CONSTRAINTS = {
    "fk_fulfillment_events_causal_reference",
    "ck_fulfillment_events_causal_reference",
    "ck_fulfillment_events_allocation_provenance",
}
EVENT_INDEXES = {
    "uq_fulfillment_events_external_id": ("organization_id", "order_id", "source", "external_event_id"),
    "ix_fulfillment_events_org_order_occurred": ("organization_id", "order_id", "occurred_at"),
    "ix_fulfillment_events_order_id": ("order_id",),
}


class PreflightError(RuntimeError):
    """A deliberately sanitized, user-facing readiness failure."""


async def event_schema_state(conn) -> str:
    """Check the complete event-model surface; reject partial 0008 migrations."""
    columns = {row.column_name: (row.data_type, row.is_nullable) for row in (
        await conn.execute(text(
            "SELECT column_name,data_type,is_nullable FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name='fulfillment_events'"))).all()}
    if any(columns.get(name) != definition for name, definition in EVENT_COLUMNS.items()):
        raise PreflightError("Fulfillment event base columns differ from current model")
    constraints = {row.conname: (row.contype, row.definition) for row in (
        await conn.execute(text(
            "SELECT conname,contype::text AS contype,pg_get_constraintdef(oid) AS definition "
            "FROM pg_constraint "
            "WHERE conrelid='fulfillment_events'::regclass"))).all()}
    if not EVENT_BASE_CHECKS <= constraints.keys() or any(
        constraints[name][0] != "c" for name in EVENT_BASE_CHECKS
    ):
        raise PreflightError("Fulfillment event baseline checks are incomplete")
    indexes = {row.indexname: row.indexdef for row in (
        await conn.execute(text(
            "SELECT indexname,indexdef FROM pg_indexes "
            "WHERE schemaname=current_schema() AND tablename='fulfillment_events'"))).all()}
    if any(name not in indexes or not all(column in indexes[name] for column in fields)
           or list(map(indexes[name].find, fields)) != sorted(map(indexes[name].find, fields))
           for name, fields in EVENT_INDEXES.items()):
        raise PreflightError("Fulfillment event indexes differ from current model")
    if "UNIQUE" not in indexes["uq_fulfillment_events_external_id"] or (
        "external_event_id IS NOT NULL" not in indexes["uq_fulfillment_events_external_id"]
    ):
        raise PreflightError("Fulfillment event partial unique index differs")
    new_column = columns.get("caused_by_event_id")
    new_constraints = EVENT_0008_CONSTRAINTS & constraints.keys()
    type_definition = constraints["ck_fulfillment_events_type"][1]
    new_types = all(value in type_definition for value in (
        "inventory_allocation_failed", "shipment_delay_attributed"))
    if new_column is None and not new_constraints and not new_types:
        return "before_0008"
    if new_column != ("uuid", "YES") or new_constraints != EVENT_0008_CONSTRAINTS or not new_types:
        raise PreflightError("Partial 0008 event migration; no automatic repair")
    if constraints["fk_fulfillment_events_causal_reference"][0] != "f" or (
        "caused_by_event_id" not in constraints["fk_fulfillment_events_causal_reference"][1]
        or "ON DELETE RESTRICT" not in constraints["fk_fulfillment_events_causal_reference"][1]
    ):
        raise PreflightError("0008 event causal foreign key differs")
    if any(constraints[name][0] != "c" for name in (
        "ck_fulfillment_events_causal_reference", "ck_fulfillment_events_allocation_provenance"
    )):
        raise PreflightError("0008 event checks differ")
    if "caused_by_event_id" not in constraints["ck_fulfillment_events_causal_reference"][1] or (
        "external_event_id" not in constraints["ck_fulfillment_events_allocation_provenance"][1]
        or "tracking_number" not in constraints["ck_fulfillment_events_allocation_provenance"][1]
    ):
        raise PreflightError("0008 event constraint definitions differ")
    return "current_0008"


async def repair_b_events() -> dict:
    """Apply 0008 only to the retained B schema, preserving its rows and 0009 runs."""
    if (ROOT / "scripts/investigation_minieval.active").exists():
        raise PreflightError("A previous evaluation is active or needs interruption review")
    state = page.state_read()
    if (state.get("database") != "ragforge_day6_test" or state.get("schema") != B_SCHEMA
            or state.get("case_id") != "59db2e27-ac93-4ef0-b939-a72ac2b5113a"
            or not state.get("prepared")):
        raise PreflightError("Retained B database, schema, or case identity differs")
    evidence = json.loads((ROOT / "scripts/investigation_minieval_B_once.json").read_text(encoding="utf-8"))
    if (evidence.get("case_id") != state["case_id"] or evidence.get("result_class") != "final_failure"
            or evidence.get("error_code") != "tool_failed"):
        raise PreflightError("Original B failure evidence differs; no repair")
    base, scoped = demo.engines(B_SCHEMA)
    try:
        async with base.connect() as conn:
            await demo.assert_database(conn)
        async with scoped.begin() as conn:
            if await conn.scalar(text("SELECT current_database()")) != "ragforge_day6_test" or (
                await conn.scalar(text("SELECT current_schema()")) != B_SCHEMA
            ):
                raise PreflightError("Refusing repair outside retained B test schema")
            case = (await conn.execute(text(
                "SELECT organization_id,order_id FROM exception_cases WHERE id=:id"),
                {"id": UUID(state["case_id"])})).one_or_none()
            if case is None or str(case.organization_id) != state["organization_id"] or (
                str(case.order_id) != state["order_id"]
            ):
                raise PreflightError("Retained B case identity differs")
            params = {"org": UUID(state["organization_id"]), "order_id": UUID(state["order_id"])}
            event_ids = {str(value) for value in (await conn.execute(text(
                "SELECT id FROM fulfillment_events WHERE organization_id=:org AND order_id=:order_id"),
                params)).scalars()}
            if event_ids != set(state["event_ids"]):
                raise PreflightError("Retained B event identities differ")
            chunk = await conn.scalar(text(
                "SELECT count(*) FROM document_chunks c JOIN documents d ON d.id=c.document_id "
                "WHERE c.id=:id AND d.workspace_id=:workspace"),
                {"id": UUID(state["sample"]["chunk_id"]),
                 "workspace": UUID(state["workspace_id"])})
            if chunk != 1:
                raise PreflightError("Retained B SOP identity differs")
            run_query = text(
                "SELECT status,error_code,response IS NULL AS response_is_null,finished_at IS NOT NULL AS finished "
                "FROM investigation_runs WHERE organization_id=:org AND requested_by_user_id=:user "
                "AND submission_key=:key")
            run_params = {"org": params["org"], "user": UUID(state["user_id"]),
                          "key": evidence["submission_key"]}
            run = (await conn.execute(run_query, run_params)).one_or_none()
            if run is None or tuple(run) != ("failed", "tool_failed", True, True):
                raise PreflightError("Original B failed run differs; no repair")
            before = await event_schema_state(conn)
            if before == "before_0008":
                path = ROOT / "backend/alembic/versions/0008_order_allocation_evidence.py"
                spec = importlib.util.spec_from_file_location("minieval_b_0008", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                def migrate(sync):
                    with Operations.context(MigrationContext.configure(sync)):
                        module.upgrade()

                await conn.run_sync(migrate)
            if await event_schema_state(conn) != "current_0008":
                raise PreflightError("0008 event schema not complete; transaction rolled back")
            after_ids = {str(value) for value in (await conn.execute(text(
                "SELECT id FROM fulfillment_events WHERE organization_id=:org AND order_id=:order_id"),
                params)).scalars()}
            if after_ids != event_ids:
                raise PreflightError("B events changed unexpectedly; transaction rolled back")
            if tuple((await conn.execute(run_query, run_params)).one()) != tuple(run):
                raise PreflightError("B failed run changed unexpectedly; transaction rolled back")
        return {"database": "ragforge_day6_test", "schema": B_SCHEMA,
                "migration": "0008_order_allocation_evidence", "before": before,
                "after": "current_0008", "retained_event_count": len(event_ids),
                "original_failed_run": "preserved"}
    finally:
        await scoped.dispose()
        await base.dispose()


async def upgrade_b_runs() -> dict:
    """Apply only the existing 0009 run-table migration to the retained B fixture."""
    if (ROOT / "scripts/investigation_minieval.active").exists():
        raise PreflightError("A previous evaluation is active or needs interruption review")
    state = page.state_read()
    if (state.get("database") != "ragforge_day6_test" or state.get("schema") != B_SCHEMA
            or state.get("case_id") != "59db2e27-ac93-4ef0-b939-a72ac2b5113a"
            or not state.get("prepared")):
        raise PreflightError("Retained B database, schema, or case identity differs")
    base, scoped = demo.engines(B_SCHEMA)
    try:
        async with base.connect() as conn:
            await demo.assert_database(conn)
        async with scoped.begin() as conn:
            if await conn.scalar(text("SELECT current_database()")) != "ragforge_day6_test" or (
                await conn.scalar(text("SELECT current_schema()")) != B_SCHEMA
            ):
                raise PreflightError("Refusing migration outside retained B test schema")
            for table in ("organizations", "users", "workspaces", "exception_cases",
                          "fulfillment_events", "documents", "document_chunks"):
                if not await conn.scalar(text(
                    "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema=current_schema() AND table_name=:name)"), {"name": table}):
                    raise PreflightError(f"B prerequisite table is absent: {table}")
            case = (await conn.execute(text(
                "SELECT organization_id, order_id FROM exception_cases WHERE id=:id"),
                {"id": UUID(state["case_id"])})).one_or_none()
            if case is None or str(case.organization_id) != state["organization_id"] or (
                str(case.order_id) != state["order_id"]
            ):
                raise PreflightError("Retained B case scope differs")
            event_count = await conn.scalar(text(
                "SELECT count(*) FROM fulfillment_events WHERE id = ANY(:ids) "
                "AND organization_id=:org AND order_id=:order_id"),
                {"ids": [UUID(value) for value in state["event_ids"]],
                 "org": UUID(state["organization_id"]), "order_id": UUID(state["order_id"])})
            if event_count != len(state["event_ids"]):
                raise PreflightError("Retained B event identity differs")
            chunk_count = await conn.scalar(text(
                "SELECT count(*) FROM document_chunks c JOIN documents d ON d.id=c.document_id "
                "WHERE c.id=:id AND d.workspace_id=:workspace"),
                {"id": UUID(state["sample"]["chunk_id"]),
                 "workspace": UUID(state["workspace_id"])})
            if chunk_count != 1:
                raise PreflightError("Retained B SOP chunk identity differs")
            if await conn.scalar(text(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
                "WHERE table_schema=current_schema() AND table_name='investigation_runs')")):
                raise PreflightError("B run table already exists; inspect it before repair")
            if await conn.scalar(text(
                "SELECT 1 FROM pg_class WHERE relnamespace=current_schema()::regnamespace "
                "AND relname='ix_investigation_runs_org_user_created'")):
                raise PreflightError("B run index name already exists; inspect partial migration")
            path = ROOT / "backend/alembic/versions/0009_investigation_runs.py"
            spec = importlib.util.spec_from_file_location("minieval_b_0009", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            def migrate(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    module.upgrade()

            await conn.run_sync(migrate)
            constraints = set((await conn.execute(text(
                "SELECT conname FROM pg_constraint WHERE conrelid='investigation_runs'::regclass"))).scalars())
            required = {"uq_investigation_runs_org_user_key", "ck_investigation_runs_status",
                        "ck_investigation_runs_result"}
            if not required <= constraints or not await conn.scalar(text(
                "SELECT to_regclass('ix_investigation_runs_org_user_created')")):
                raise PreflightError("0009 run table constraints or index incomplete; transaction rolled back")
        return {"database": "ragforge_day6_test", "schema": B_SCHEMA,
                "migration": "0009_investigation_runs", "run_table": "created",
                "existing_case_events_sop": "preserved"}
    finally:
        await scoped.dispose()
        await base.dispose()


def fixture(case_key: str) -> dict:
    state = (allocation.state_read() if case_key in ("A", "C") else page.state_read()).copy()
    if not state.get("prepared") or state["database"] != "ragforge_day6_test":
        raise PreflightError("Retained isolated fixture is not ready")
    login = demo.load_state()
    if state["organization_id"] != login["organization_id"] or state["user_id"] != login["member_id"]:
        raise PreflightError("Retained user and organization scope differ")
    if case_key == "C":
        state["case_id"] = str(ABSENT_CASE_ID)
        state["as_of"] = allocation.state_read()["as_of"]
    elif case_key in ("B", "B2"):
        state["as_of"] = B_AS_OF
    if case_key in ("A", "C"):
        allocation.configure(state)
    else:
        page.configure(state["collection"])
    return state


def classify(case_key: str, body: dict, trace: list[dict], rejections: list[dict]) -> str:
    report = validate_report(json.dumps(body["report"]), trace)
    if render_report(report, trace) != body["handoff"]:
        raise ValueError("Handoff differs from validated report")
    if (report.outcome, report.root_cause) != EXPECTED[case_key]:
        raise ValueError("Report differs from case expectation")
    if case_key in ("A", "B", "B2") and not report.knowledge_source_ids:
        raise ValueError("Required independent SOP citation is missing")
    if case_key == "C" and report.evidence_event_ids:
        raise ValueError("Absent case invented business citations")
    return ("corrected_pass" if any(row.get("phase") == "report" for row in rejections)
            else "first_answer_pass")


async def preflight(case_key: str) -> dict:
    """Check real scope and dependencies without mutating the fixture."""
    if (ROOT / "scripts/investigation_minieval.active").exists():
        raise PreflightError("A previous evaluation is active or needs interruption review")
    state = fixture(case_key)
    base, scoped = demo.engines(state["schema"])
    try:
        async with base.connect() as conn:
            await demo.assert_database(conn)
        async with scoped.connect() as conn:
            if await conn.scalar(text("SELECT current_schema()")) != state["schema"]:
                raise PreflightError("Wrong isolated schema")
            if not await conn.scalar(text(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
                "WHERE table_schema=current_schema() AND table_name='investigation_runs')")):
                raise PreflightError("Investigation runs table is absent in retained schema")
            active = await conn.scalar(text("SELECT count(*) FROM investigation_runs "
                                            "WHERE status='running' AND deadline_at>now()"))
            if active:
                raise PreflightError("Another investigation is still active in this schema")
            try:
                # Exercise the mapped SELECT, including columns a raw SELECT id misses.
                await conn.execute(select(FulfillmentEvent).where(
                    FulfillmentEvent.organization_id == UUID(state["organization_id"]),
                    FulfillmentEvent.order_id == UUID(state["order_id"])).limit(1))
            except ProgrammingError:
                raise PreflightError("FulfillmentEvent ORM schema is incompatible") from None
            if await event_schema_state(conn) != "current_0008":
                raise PreflightError("Fulfillment event schema predates 0008")
            member = await conn.scalar(text("SELECT count(*) FROM organization_members "
                                            "WHERE organization_id=:org AND user_id=:user"),
                                       {"org": UUID(state["organization_id"]), "user": UUID(state["user_id"])})
            workspace = await conn.scalar(text("SELECT count(*) FROM workspaces w "
                                               "JOIN workspace_members m ON m.workspace_id=w.id "
                                               "WHERE w.id=:workspace AND w.organization_id=:org AND m.user_id=:user"),
                                          {"workspace": UUID(state["workspace_id"]),
                                           "org": UUID(state["organization_id"]),
                                           "user": UUID(state["user_id"])})
            if member != 1 or workspace != 1:
                raise PreflightError("Enterprise or workspace membership is missing")
            case = (await conn.execute(text("SELECT organization_id,order_id FROM exception_cases WHERE id=:id"),
                                       {"id": UUID(state["case_id"])})).one_or_none()
            if case_key == "C":
                if case is not None:
                    raise PreflightError("Fixed not_found case unexpectedly exists")
                event_count = 0
            else:
                if case is None or str(case.organization_id) != state["organization_id"] or str(case.order_id) != state["order_id"]:
                    raise PreflightError("Case/order/organization scope differs")
                rows = (await conn.execute(text("SELECT id FROM fulfillment_events "
                                                "WHERE organization_id=:org AND order_id=:order_id "
                                                "AND occurred_at<=:as_of"),
                                           {"org": UUID(state["organization_id"]),
                                            "order_id": UUID(state["order_id"]),
                                            "as_of": datetime.fromisoformat(state["as_of"])})).scalars().all()
                if {str(value) for value in rows} != set(state["event_ids"]):
                    raise PreflightError("Observed event IDs or analysis time differ")
                event_count = len(rows)
            chunk = await conn.scalar(text("SELECT count(*) FROM document_chunks c "
                                           "JOIN documents d ON d.id=c.document_id "
                                           "WHERE c.id=:chunk AND d.workspace_id=:workspace "
                                           "AND d.status='completed'"),
                                      {"chunk": UUID(state["sample"]["chunk_id"]),
                                       "workspace": UUID(state["workspace_id"])})
            if chunk != 1:
                raise PreflightError("Authorized SOP chunk is absent")
        qdrant = AsyncQdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)
        try:
            if not await qdrant.collection_exists(state["collection"]):
                raise PreflightError("SOP collection is absent")
            points = await qdrant.retrieve(state["collection"], ids=[state["sample"]["vector_id"]])
            if len(points) != 1:
                raise PreflightError("SOP vector point is absent")
        finally:
            await qdrant.close()
        redis = Redis.from_url(settings.REDIS_URL)
        try:
            if not await redis.ping():
                raise PreflightError("Redis PING failed")
        finally:
            await redis.aclose()
        async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL, timeout=8) as client:
            for model in (settings.LLM_MODEL, settings.EMBEDDING_MODEL):
                response = await client.post("/api/show", json={"model": model})
                response.raise_for_status()  # Metadata only; no model generation.
        return {"case_key": case_key, "database": "ragforge_day6_test", "schema": state["schema"],
                "case_id": state["case_id"], "case_exists": case_key != "C",
                "event_count": event_count, "organization_member": True,
                "workspace_member": True, "sop_chunk_and_vector": True,
                "qdrant": "ok", "redis": "PONG", "ollama_models": "metadata_available"}
    finally:
        await scoped.dispose()
        await base.dispose()


class Evidence:
    def __init__(self, case_key: str, state: dict):
        stem = ROOT / "scripts" / f"investigation_minieval_{case_key}_once"
        self.snapshot, self.events = stem.with_suffix(".json"), stem.with_suffix(".jsonl")
        version = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                 capture_output=True, text=True, check=False)
        # An existing attempt, including an interrupted one, is never overwritten.
        with self.snapshot.open("x", encoding="utf-8") as stream:
            self.data = {"case_key": case_key, "case_id": state["case_id"],
                         "code_commit": version.stdout.strip() if version.returncode == 0 else None,
                         "provider_kind": "real_ollama", "model": settings.LLM_MODEL,
                         "environment": "isolated_postgres_authenticated_asgi_api",
                         "organization_id": state["organization_id"],
                         "workspace_id": state["workspace_id"], "as_of": state["as_of"],
                         "require_knowledge": case_key != "C", "started_at": datetime.now(UTC).isoformat(),
                         "result_class": None, "attempt_status": "reserved",
                         "trace": [], "rejections": [],
                         "model_timings": [], "tool_timings": [], "phase_changes": [],
                         "submission_key": "minieval-" + case_key.lower() + "-" + uuid4().hex,
                         "events_path": str(self.events.relative_to(ROOT))}
            json.dump(self.data, stream, ensure_ascii=False, indent=2)
        with self.events.open("x", encoding="utf-8"):
            pass
        self.phase, self.model_index = "investigation", 0
        self.emit("attempt_reserved")

    def save(self):
        temporary = self.snapshot.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temporary.replace(self.snapshot)

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
        elif name in ("model_completed", "model_cancelled"):
            self.data["model_timings"].append(values)
        elif name == "tool_completed":
            self.data["tool_timings"].append(values)
        elif name == "phase_changed":
            self.phase = "report" if values["final_only"] else "investigation"
            self.data["phase_changes"].append(values)
        self.save()


async def run(case_key: str):
    stem = ROOT / "scripts" / f"investigation_minieval_{case_key}_once"
    attempt_path = stem.with_suffix(".active")
    if (stem.with_suffix(".json").exists() or stem.with_suffix(".jsonl").exists()
            or attempt_path.exists()):
        raise PreflightError("This case already has an attempt; inspect its original evidence")
    state = fixture(case_key)
    # Preflight before reserving the only attempt; no fixture or service repair.
    ready = await preflight(case_key)
    active_path = ROOT / "scripts/investigation_minieval.active"
    with active_path.open("x", encoding="utf-8") as active_stream:
        active_stream.write(json.dumps({"case_key": case_key,
                                        "at": datetime.now(UTC).isoformat()}))
    try:
        with attempt_path.open("x", encoding="utf-8") as attempt_stream:
            attempt_stream.write(json.dumps({"case_key": case_key,
                                             "at": datetime.now(UTC).isoformat()}))
        evidence = Evidence(case_key, state)
    except BaseException:
        attempt_path.unlink(missing_ok=True)
        active_path.unlink()
        raise
    evidence.data["preflight"] = ready
    evidence.save()
    _, scoped = demo.engines(state["schema"])
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(demo.api_router, prefix="/api/v1")

    async def isolated_db():
        async with AsyncSession(scoped, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    original_graph, original_session = investigations.run_core_agent, core_graph.CoreSession
    original_tool = StructuredTool.ainvoke
    core_graph.CoreSession = page.ObservedCoreSession

    async def timed_tool(tool, *args, **kwargs):
        started = time.monotonic()
        try:
            result = await original_tool(tool, *args, **kwargs)
        except Exception as exc:
            evidence.emit("tool_completed", tool=tool.name,
                          elapsed_seconds=round(time.monotonic() - started, 3),
                          exception_type=type(exc).__name__)
            raise
        evidence.emit("tool_completed", tool=tool.name,
                      elapsed_seconds=round(time.monotonic() - started, 3),
                      status=result.get("status") if isinstance(result, dict) else None)
        return result

    async def observed_graph(provider, db, **kwargs):
        request_id = get_contextvars().get("request_id")
        evidence.data["request_id"] = request_id
        token = page.ACTIVE_EVIDENCE.set(evidence)
        started = time.monotonic()
        try:
            result = await original_graph(allocation.TimedProvider(provider, evidence), db, **kwargs)
            evidence.data.update(trace=result.trace, report=result.report,
                                 handoff=result.answer, model_call_count=result.model_requests,
                                 rejected_finals=result.rejected_finals)
            return result
        except CoreAgentError as exc:
            evidence.data.update(trace=exc.trace, error_code=exc.error_code,
                                 model_call_count=exc.model_requests,
                                 rejected_finals=getattr(exc, "rejected_finals", []))
            raise
        finally:
            page.ACTIVE_EVIDENCE.reset(token)
            evidence.data["graph_elapsed_seconds"] = round(time.monotonic() - started, 3)
            evidence.save()

    StructuredTool.ainvoke = timed_tool
    investigations.run_core_agent = observed_graph
    started = time.monotonic()
    try:
        login_state = demo.load_state()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://minieval.local",
                               timeout=httpx.Timeout(735.0)) as client:
            login = await client.post("/api/v1/auth/login", data={
                "username": login_state["emails"]["member"], "password": login_state["password"]})
            login.raise_for_status()
            token = login.json()["access_token"]
            evidence.emit("authenticated")  # Never store password or JWT.
            evidence.data["attempt_status"] = "running"
            evidence.emit("investigation_post_started")
            response = await asyncio.wait_for(client.post(
                f"/api/v1/organizations/{state['organization_id']}/investigations",
                headers={"Authorization": f"Bearer {token}",
                         "Idempotency-Key": evidence.data["submission_key"]},
                json={"case_id": state["case_id"], "workspace_id": state["workspace_id"],
                      "as_of": state["as_of"], "require_knowledge": case_key != "C"}), timeout=735)
            evidence.data["http_status"] = response.status_code
            evidence.data["request_id_header"] = response.headers.get("x-request-id")
            body = response.json()
            if response.status_code != 200 or "report" not in body:
                evidence.data["error_code"] = body.get("error", {}).get("code", "unexpected_http_result")
                evidence.data["failure_phase"] = evidence.phase
                evidence.data["failure_reason"] = evidence.data["error_code"]
                return
            evidence.data.update(report=body["report"], handoff=body["handoff"],
                                 run_id=body.get("run_id"), request_id=body.get("request_id"),
                                 result_class=classify(case_key, body, evidence.data["trace"],
                                                       evidence.data["rejections"]))
        evidence.emit("investigation_post_finished", status=evidence.data.get("http_status"))
    except Exception as exc:  # noqa: BLE001 -- preserve a single failed evaluation attempt
        evidence.data.update(result_class="final_failure", exception_type=type(exc).__name__,
                             error_code=evidence.data.get("error_code") or "evaluation_exception",
                             failure_phase=evidence.phase,
                             failure_reason=str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
        evidence.emit("attempt_exception", exception_type=type(exc).__name__)
    finally:
        if evidence.data["result_class"] is None:
            evidence.data["result_class"] = "final_failure"
        evidence.data["attempt_status"] = "finished"
        evidence.data["elapsed_seconds"] = round(time.monotonic() - started, 3)
        evidence.data["finished_at"] = datetime.now(UTC).isoformat()
        evidence.data.setdefault("model_call_count", len(evidence.data["model_timings"]))
        evidence.emit("attempt_finished", result_class=evidence.data["result_class"],
                      error_code=evidence.data.get("error_code"))
        investigations.run_core_agent = original_graph
        core_graph.CoreSession = original_session
        StructuredTool.ainvoke = original_tool
        await scoped.dispose()
        attempt_path.unlink()
        active_path.unlink()
        print(json.dumps({key: evidence.data.get(key) for key in (
            "case_key", "result_class", "request_id", "http_status", "error_code",
            "model_call_count", "elapsed_seconds")}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "run", "upgrade-b", "repair-b"))
    parser.add_argument("--case", choices=tuple(EXPECTED))
    args = parser.parse_args()
    if (args.command in ("upgrade-b", "repair-b")) != (args.case is None):
        parser.error("repair/upgrade has no case; preflight/run require --case")
    try:
        if args.command == "upgrade-b":
            print(json.dumps(asyncio.run(upgrade_b_runs()), ensure_ascii=False))
        elif args.command == "repair-b":
            print(json.dumps(asyncio.run(repair_b_events()), ensure_ascii=False))
        elif args.command == "preflight":
            print(json.dumps(asyncio.run(preflight(args.case)), ensure_ascii=False))
        else:
            asyncio.run(run(args.case))
    except Exception as exc:  # noqa: BLE001 -- stop without printing connection strings or tokens
        print(json.dumps({"case_key": args.case, "status": "failed",
                          "error_type": type(exc).__name__,
                          "reason": str(exc) if isinstance(exc, PreflightError) else "dependency_or_evaluation_error"},
                         ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
