"""One real authenticated C03 or C05 API request; guarded PG, no business mocks.

The parent bounds the child to 690s and reserves 30s for cleanup verification.
Only get_db is bound to the fixture's transaction. Profiling observes original
functions without replacing Agent, Provider, Tool, Service or business queries.
"""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from day13_e2e import OBSERVED, ROOT, Day8PostgresTests, OllamaProvider, seed, settings
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

BOOTSTRAP_ROOT = ROOT  # Bootstrap pins DATABASE_URL before importing app modules.

from app.ai.agents.core_agent import CoreAgentResult, run_core_agent
from app.ai.llm.base import LLMToolResponse
from app.ai.llm.factory import get_llm_provider
from app.api.deps import get_current_user
from app.api.v1.router import api_router
from app.core.exceptions import register_exception_handlers
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.middleware.request_context import RequestContextMiddleware
from app.models.organization import OrganizationMember
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.services.organization_service import require_role
from app.services.workspace_service import require_workspace_role


def save(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def event(path, name, **values):
    row = {"at": datetime.now(UTC).isoformat(), "event": name, **values}
    with path.with_suffix(".jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()


class Observer:
    """Read only allowlisted locals/results; never record JWTs/passwords/settings."""

    def __init__(self, path, data, provider=None):
        self.path, self.data = path, data
        self.frames = {}
        self.model_code = type(provider).generate_with_tools.__code__ if provider else OllamaProvider.generate_with_tools.__code__
        self.codes = {self.model_code, run_core_agent.__code__,
                      get_current_user.__code__, require_role.__code__, require_workspace_role.__code__}

    def __call__(self, frame, action, value):
        if action not in ("call", "return") or frame.f_code not in self.codes:
            return
        try:
            self.observe(frame, action, value)
        except Exception as exc:  # noqa: BLE001 -- observer must not alter the request
            self.data.setdefault("observer_errors", []).append(type(exc).__name__)

    def observe(self, frame, action, value):
        local = frame.f_locals
        if frame.f_code is self.model_code:
            if frame not in self.frames:
                entry = {"index": len(self.data["requests"]) + 1,
                         "offered_tools": [t.name for t in local["tools"]],
                         "observed_tools": [s["tool"] for s in self.data.get("trace", [])]}
                self.frames[frame] = (time.monotonic(), entry)
                self.data["requests"].append(entry)
                event(self.path, "model_request_started", **entry)
            if action == "return" and isinstance(value, LLMToolResponse):
                started, entry = self.frames[frame]
                entry.update(elapsed_seconds=round(time.monotonic() - started, 3),
                             response=asdict(value))
                event(self.path, "model_request_completed", **entry)
        elif frame.f_code is run_core_agent.__code__:
            if "agent_input" not in self.data:
                self.data["agent_input"] = {k: str(local[k]) for k in
                                            ("organization_id", "case_id", "as_of", "user_id", "workspace_id") if k in local}
                event(self.path, "agent_entered", **self.data["agent_input"])
            trace = local.get("trace", [])
            for step in trace[len(self.data.get("trace", [])):]:
                event(self.path, "tool_observed", **step)
            self.data["trace"] = list(trace)
            self.data["rejected_finals"] = list(local.get("rejected", []))
            self.data["model_requests"] = local.get("requests", 0)
            if action == "return" and isinstance(value, CoreAgentResult):
                self.data.update(asdict(value))
                event(self.path, "validated_core_report", report=value.report)
        elif action == "return" and isinstance(value, WorkspaceMember):
            self.data["verified_workspace_membership"] = {
                "workspace_id": str(value.workspace_id), "user_id": str(value.user_id), "role": value.role}
            event(self.path, "workspace_membership_verified", **self.data["verified_workspace_membership"])
        elif action == "return" and isinstance(value, OrganizationMember):
            self.data["verified_membership"] = {
                "id": str(value.id), "organization_id": str(value.organization_id),
                "user_id": str(value.user_id), "role": value.role}
            event(self.path, "membership_verified", **self.data["verified_membership"])
        elif action == "return" and isinstance(value, User):
            self.data["authenticated_user_id"] = str(value.id)
            event(self.path, "jwt_user_verified", user_id=str(value.id))


def verify(data):
    """Keep day13 C03 assertions and add API transport/handoff assertions."""
    trace, report, answer = data["trace"], data["report"], data["answer"]
    path = [s["tool"] for s in trace if s["result"]["status"] != "invalid_input"]
    assert sum(s["result"]["status"] == "invalid_input" for s in trace) <= 1
    assert path == ["get_exception_case", "analyze_fulfillment", "get_inventory_status"]
    assert report["outcome"] == "insufficient_evidence"
    assert report["root_cause"] == "unknown"
    assert report["evidence_event_ids"]
    for identifier in report["evidence_event_ids"]:
        assert identifier in answer
    inventory = next(s["result"]["inventory"] for s in trace
                     if s["tool"] == "get_inventory_status")
    assert inventory["available_quantity"] == -3
    assert inventory["observed_at"] in answer
    verify_api(data)
    assert "不能证明本订单缺货" in answer
    assert "建议，尚未执行" in answer
    assert data["model_requests"] == len(data["requests"])
    reports = [r for r in data["requests"] if "get_inventory_status" in r["observed_tools"]]
    assert reports and all(r["offered_tools"] == [] for r in reports)
    assert not data.get("observer_errors")
    data["tool_path"] = path


def verify_api(data):
    """Shared transport/authenticated organization and six-part handoff contract."""
    report, answer = data["report"], data["answer"]
    assert data["http_status"] == 200
    body = data["api_response"]
    assert body["report"] == report and body["handoff"] == answer
    assert body["request_id"] == data["request_id"] == data["response_request_id"]
    assert data["authenticated_user_id"] == data["verified_membership"]["user_id"]
    assert data["agent_input"]["organization_id"] == data["verified_membership"]["organization_id"]
    assert body["organization_id"] == data["agent_input"]["organization_id"]
    assert not ({"trace", "prompt", "model_final", "rejected_finals"} & body.keys())
    for heading in ("已确认事实", "证据引用及观察时间", "不能确认的事项", "缺少的资料",
                    "与资料缺口逐项对应的下一步建议", "处理状态"):
        assert heading in answer


async def child(path, extension=None):
    started = time.monotonic()
    scenario = "C05" if extension else "C03"
    data = {"scenario": scenario, "passed": False, "error_code": None,
            "pid": os.getpid(), "request_id": str(uuid4()), "requests": [],
            "rollback_verified": False, "database": "ragforge_day6_test",
            "boundary": "real JWT/member/API/Core/Ollama/Tool/Service/PG; ASGI; isolated get_db"}
    save(path, data)
    event(path, "run_started", pid=os.getpid(), request_id=data["request_id"])
    # Same local model settings as the existing day13 runner.
    settings.LLM_PROVIDER = "ollama"
    settings.LLM_MODEL = "llama3.1:8b"
    settings.OLLAMA_BASE_URL = "http://localhost:11434"
    settings.LLM_MAX_TOKENS = 700
    settings.LLM_REQUEST_TIMEOUT_SECONDS = 190
    provider = get_llm_provider()
    assert type(provider) is OllamaProvider
    stage = "isolated_setup"
    try:
        if extension:
            await extension.preflight(data, lambda: save(path, data))
            event(path, "knowledge_preflight", **data["preflight"])
        async with Day8PostgresTests().database("migration") as (conn, org, order, helper, _):
            try:
                data["schema"] = await conn.scalar(text("SELECT current_schema()"))
                data["pg_backend_pid"] = await conn.scalar(text("SELECT pg_backend_pid()"))
                save(path, data)
                event(path, "schema_created", schema=data["schema"], pg_backend_pid=data["pg_backend_pid"])
                case_id = (await extension.seed(conn, org, order, helper, data) if extension else
                           await seed(conn, org, order, helper, "C03"))
                data["case_id"] = str(case_id)
                for name in ("users", "organization_members", "refresh_tokens"):
                    await conn.run_sync(Base.metadata.tables[name].create)
                user_id, password = uuid4(), uuid4().hex
                email = f"api-{scenario.lower()}-{user_id}@example.invalid"
                await conn.execute(insert(Base.metadata.tables["users"]).values(
                    id=user_id, email=email, hashed_password=hash_password(password),
                    full_name=f"Isolated API {scenario}", is_active=True))
                await conn.execute(insert(Base.metadata.tables["organization_members"]).values(
                    id=uuid4(), organization_id=org, user_id=user_id, role="member"))
                payload = {"case_id": str(case_id), "as_of": OBSERVED.isoformat()}
                if extension:
                    stage = "knowledge_setup"
                    await extension.prepare(conn, org, user_id, data, lambda: save(path, data))
                    payload["workspace_id"] = data["workspace_id"]
                    payload["require_knowledge"] = True
                    event(path, "knowledge_prepared", workspace_id=data["workspace_id"],
                          collection=data["collection"], sample=data["sample"])
                async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint",
                                        expire_on_commit=False) as db:
                    async def isolated_db():
                        yield db

                    app = FastAPI()
                    register_exception_handlers(app)
                    app.add_middleware(RequestContextMiddleware)
                    app.include_router(api_router, prefix="/api/v1")
                    app.dependency_overrides[get_db] = isolated_db
                    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                                           base_url="http://isolated") as client:
                        stage = "login"
                        login = await client.post("/api/v1/auth/login",
                                                  data={"username": email, "password": password})
                        data["login_status"] = login.status_code
                        assert login.status_code == 200
                        headers = {"Authorization": "Bearer " + login.json()["access_token"],
                                   "X-Request-ID": data["request_id"]}
                        await conn.execute(text("SET LOCAL transaction_read_only = on"))
                        stage = "investigation_api"
                        observer = Observer(path, data, provider)
                        before = time.monotonic()
                        sys.setprofile(observer)
                        try:
                            response = await asyncio.wait_for(client.post(
                                f"/api/v1/organizations/{org}/investigations",
                                json=payload,
                                headers=headers), timeout=600)
                        finally:
                            sys.setprofile(None)
                            data["api_elapsed_seconds"] = round(time.monotonic() - before, 3)
                            for model_started, entry in observer.frames.values():
                                if "elapsed_seconds" not in entry:
                                    entry.update(elapsed_seconds=round(time.monotonic() - model_started, 3),
                                                 completed=False)
                        data.update(http_status=response.status_code, api_response=response.json(),
                                    response_request_id=response.headers.get("X-Request-ID"))
                        event(path, "api_returned", status=response.status_code, body=response.json())
                        if response.status_code != 200:
                            data["error_code"] = response.json().get("error", {}).get("code")
                            raise RuntimeError("API did not return a validated report")
                        stage = "acceptance_assertions"
                        if extension:
                            verify_api(data)
                            extension.verify(data)
                        else:
                            verify(data)
                        data["passed"] = True
            except Exception as exc:  # noqa: BLE001 -- preserve evidence, then verify rollback
                data.update(passed=False, failure_stage=stage, failure_type=type(exc).__name__)
                if isinstance(exc, TimeoutError):
                    data["error_code"] = "request_timeout"
                event(path, "run_failed", stage=stage, failure_type=type(exc).__name__)
            finally:
                save(path, data)
        data["rollback_verified"] = True
        event(path, "rollback_verified", schema=data.get("schema"))
    except Exception as exc:  # noqa: BLE001 -- record structural cleanup/setup failure only
        data.update(passed=False, cleanup_or_setup_failure=type(exc).__name__)
    finally:
        if extension:
            try:
                await extension.close(data)
            except Exception as exc:  # noqa: BLE001 -- cleanup failure is never a pass
                data.update(passed=False, knowledge_cleanup_failure=type(exc).__name__)
        await provider._client.aclose()
        data["elapsed_seconds"] = round(time.monotonic() - started, 3)
        save(path, data)
        event(path, "child_finished", passed=data["passed"], rollback_verified=data["rollback_verified"])
    return 0 if data["passed"] and data["rollback_verified"] else 1


async def check_cleanup(data):
    url = make_url(os.environ["DAY6_TEST_DATABASE_URL"])
    assert url.drivername == "postgresql+asyncpg" and url.database == "ragforge_day6_test"
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT current_database()")) == "ragforge_day6_test"
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            data["schema_absent_after_exit"] = not await conn.scalar(text(
                "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:name)"),
                {"name": data.get("schema", "")}) if data.get("schema") else None
            data["pg_session_absent_after_exit"] = not await conn.scalar(text(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE pid=:pid)"),
                {"pid": data.get("pg_backend_pid", -1)})
            await conn.rollback()
    finally:
        await engine.dispose()


def stop_child_tree(process):
    """The Windows venv launcher may own another Python process holding the PG transaction."""
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True, timeout=5, check=False,
        )
        if result.returncode != 0 and process.poll() is None:
            raise RuntimeError("Could not stop the owned test process tree")
    else:
        process.kill()
    process.wait(timeout=5)


def wait_for_child_deadline(process, timeout=690):
    """Recheck monotonic deadline even when a native wait returns a child exit.

    A paused/suspended parent cannot enforce a deadline until scheduled again.
    Short waits allow it to notice an elapsed deadline on its next runnable turn.
    """
    started = time.monotonic()
    deadline = started + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            process.wait(timeout=min(1.0, remaining))
        except subprocess.TimeoutExpired:
            continue
        break
    elapsed = time.monotonic() - started
    exceeded = elapsed >= timeout
    # A late exit still exceeded the deadline, but must not trigger taskkill
    # against an already-exited (and potentially recycled) PID.
    stopped = exceeded and process.poll() is None
    if stopped:
        stop_child_tree(process)
    return {"outer_timeout": exceeded, "child_wait_elapsed_seconds": round(elapsed, 3),
            "child_timeout_seconds": timeout, "child_tree_stop_requested": stopped}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", type=Path)
    parser.add_argument("--case", choices=("C03", "C05"), default="C03")
    args = parser.parse_args()
    extension = None
    if args.case == "C05":
        from investigation_c05 import Scenario
        extension = Scenario()
    if args.child:
        return asyncio.run(child(args.child, extension))
    started = time.monotonic()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = ROOT / "scripts" / f"investigation_api_{args.case.lower()}_{stamp}.json"
    print(f"EVIDENCE={path}", flush=True)
    with path.with_suffix(".log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", str(path), "--case", args.case],
                                   stdout=log, stderr=log)
        timed_out = False
        wait_details = {}
        if extension:
            event(path, "parent_wait_started", parent_pid=os.getpid(), child_launcher_pid=process.pid,
                  timeout_seconds=690, clock=time.get_clock_info("monotonic").implementation)
            wait_details = wait_for_child_deadline(process, timeout=690)
            timed_out = wait_details["outer_timeout"]
            event(path, "parent_wait_finished", **wait_details)
        else:
            try:
                process.wait(timeout=690)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                process.wait(timeout=5)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"passed": False}
    data.update(process_exit_code=process.returncode, process_exited=process.poll() is not None,
                outer_timeout=timed_out)
    data.update(wait_details)
    if timed_out:
        data["child_error_code"] = data.get("error_code")
        data.update(passed=False, error_code="outer_timeout")
    async def cleanup():
        try:
            await check_cleanup(data)
        finally:
            if extension:
                await extension.cleanup_after_exit(data)

    try:
        asyncio.run(asyncio.wait_for(cleanup(), timeout=20))
    except Exception as exc:  # noqa: BLE001 -- preserve result if cleanup cannot be confirmed
        data.update(passed=False, cleanup_verification_error=type(exc).__name__)
    if data.get("schema_absent_after_exit") is not True or not data.get("pg_session_absent_after_exit"):
        data["passed"] = False
    if extension and (data.get("collection_absent") is not True or
                      data.get("rollback_verified") is not True or process.returncode != 0):
        data["passed"] = False
    data["total_elapsed_seconds"] = round(time.monotonic() - started, 3)
    data["source_sha256"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
        "scripts/investigation_api_c03_once.py", "scripts/day13_e2e.py",
        "backend/app/api/v1/endpoints/investigations.py", "backend/app/ai/agents/core_agent.py",
        "backend/app/ai/agents/investigation_report.py", "backend/app/ai/tools/investigation_tools.py")}
    if extension:
        for name in ("scripts/investigation_c05.py", "scripts/knowledge_retrieval_verify.py",
                     "backend/app/ai/tools/knowledge_tool.py", "backend/app/ai/graph/nodes.py"):
            data["source_sha256"][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    event(path, "process_and_cleanup_checked", process_exit_code=process.returncode,
          schema_absent=data.get("schema_absent_after_exit"),
          pg_session_absent=data.get("pg_session_absent_after_exit"), outer_timeout=timed_out)
    save(path, data)
    print(json.dumps({k: data.get(k) for k in ("passed", "error_code", "total_elapsed_seconds",
          "rollback_verified", "schema_absent_after_exit", "process_exit_code")}), flush=True)
    return 0 if data["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
