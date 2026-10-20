"""C10: real isolated auth/retrieval; controlled chat captures every model input."""

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
from unittest.mock import patch
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import investigation_api_c03_once as base
from app.ai.agents.investigation_report import evidence_contract
from app.ai.llm.base import LLMToolCall, LLMToolResponse
from app.ai.tools.knowledge_tool import create_search_knowledge_tool
from app.core.redis_client import get_redis_client
from app.core.security import hash_password
from app.models.exception_case import ExceptionCase
from app.models.workspace import WorkspaceMember
from investigation_c05 import Scenario
from knowledge_retrieval_verify import Observer, index_samples, seed
from sqlalchemy import insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

QUERY = "Inventory discrepancy SOP: how to check stock count and reservation ledger?"


class Evidence:
    def __init__(self, path):
        self.path = path
        self.data = {"scenario": "C10", "passed": False, "pid": os.getpid(),
                     "rollback_verified": False, "checks": {}, "calls": [], "api_runs": {}}

    def save(self):
        base.save(self.path, self.data)

    def event(self, name, **values):
        base.event(self.path, name, **values)


def verify_model_visibility(requests, allowed, denied):
    """Inspect every actual input, including system, tool schemas and tool messages."""
    serialized = json.dumps(requests, ensure_ascii=False)
    forbidden = [denied[k] for k in
                 ("chunk_id", "document_id", "vector_id", "document_filename", "content")]
    forbidden.append("RESTRICTED-B")
    assert all(value not in serialized for value in forbidden), "Unauthorized data entered model input"
    observations = [json.loads(m["content"]) for r in requests for m in r["messages"]
                    if m["role"] == "tool" and m["tool_name"] == "search_knowledge"]
    assert observations and all(o["status"] == "found" for o in observations)
    for observation in observations:
        assert len(observation["sources"]) == 1
        assert all(observation["sources"][0][k] == allowed[k]
                   for k in ("chunk_id", "document_id", "document_filename", "content"))
    return {"allowed_source_visible": True, "foreign_ids_body_filename_absent_from_all_inputs": True}


class ControlledProvider:
    """Only chat is substituted; decisions use actual received tool messages."""
    def __init__(self, evidence, label):
        self.evidence, self.label = evidence, label
        self.requests = []

    async def generate_with_tools(self, *, messages, tools, system, **kwargs):
        self.requests.append({"messages": [asdict(m) for m in messages],
                              "tools": [asdict(t) for t in tools], "system": system})
        self.evidence.data["api_runs"][self.label]["model_inputs"] = self.requests
        self.evidence.save()
        trace = [{"tool": m.tool_name, "result": json.loads(m.content)}
                 for m in messages if m.role == "tool"]
        task = json.loads(messages[0].content)
        if not trace:
            name, arguments = "get_exception_case", {"case_id": task["case_id"]}
        elif len(trace) == 1:
            name, arguments = "analyze_fulfillment", {
                "order_id": trace[0]["result"]["case"]["order_id"], "as_of": task["as_of"]}
        elif len(trace) == 2:
            name, arguments = "search_knowledge", {"query": QUERY}
        else:
            assert tools == []
            return LLMToolResponse(json.dumps(evidence_contract(trace)), "controlled-c10", "stop")
        assert name in {t.name for t in tools}
        return LLMToolResponse("", "controlled-c10", "tool_use",
                               [LLMToolCall(str(uuid4()), name, arguments)])


async def exercise(conn, org, order, helper, resources, evidence):
    data = evidence.data
    user, own, other, empty, samples = await seed(conn, org)
    data.update(user_id=str(user), organization_id=str(org), samples=samples,
                workspaces={"authorized": str(own), "unauthorized": str(other), "empty": str(empty)})
    data["memberships"] = [{"workspace_id": str(row.workspace_id), "user_id": str(row.user_id), "role": row.role}
                           for row in (await conn.execute(select(WorkspaceMember))).mappings()]
    await conn.run_sync(base.Base.metadata.tables["refresh_tokens"].create)
    password = uuid4().hex
    await conn.execute(update(base.User).where(base.User.id == user).values(hashed_password=hash_password(password)))
    case = helper.case(org, order)
    case.update(problem_description="Consult authorized inventory review rules. Cause unconfirmed.",
                opened_at=base.OBSERVED)
    await conn.execute(insert(ExceptionCase).values(**case))
    data["case_id"] = str(case["id"])
    evidence.save()
    observer = Observer(evidence, resources.embedding, resources.store)
    sys.setprofile(observer)
    try:
        data["stage"] = "index_documents"
        await resources.store.ensure_collection()
        data["indexed_chunk_ids"] = await index_samples(resources.embedding, resources.store, samples)
        async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False) as db:
            async def isolated_db():
                yield db

            app = base.FastAPI()
            base.register_exception_handlers(app)
            app.add_middleware(base.RequestContextMiddleware)
            app.include_router(base.api_router, prefix="/api/v1")
            app.dependency_overrides[base.get_db] = isolated_db
            async with base.AsyncClient(transport=base.ASGITransport(app=app, raise_app_exceptions=False),
                                        base_url="http://isolated") as client:
                data["stage"] = "login"
                response = await client.post("/api/v1/auth/login", data={
                    "username": f"knowledge-{user}@example.invalid", "password": password})
                data["login_status"] = response.status_code
                assert response.status_code == 200
                headers = {"Authorization": "Bearer " + response.json()["access_token"]}
                await conn.execute(text("SET LOCAL transaction_read_only = on"))

                async def request(workspace, label):
                    data["stage"] = label
                    data["api_runs"][label] = {}
                    provider = ControlledProvider(evidence, label)
                    with patch("app.api.v1.endpoints.investigations.get_llm_provider", return_value=provider) as factory:
                        response = await client.post(f"/api/v1/organizations/{org}/investigations",
                            json={"case_id": str(case["id"]), "workspace_id": str(workspace),
                                  "require_knowledge": True, "as_of": base.OBSERVED.isoformat()}, headers=headers)
                    data["api_runs"][label].update(status=response.status_code, response=response.json(),
                                                  provider_factory_calls=factory.call_count)
                    evidence.save()
                    return response, provider

                with patch("app.ai.graph.nodes.get_llm_provider", side_effect=AssertionError("Chat forbidden")):
                    response, provider = await request(own, "authorized")
                    assert response.status_code == 200
                    data["checks"]["authorized_api_context"] = verify_model_visibility(provider.requests, *samples)
                    searches = [c for c in data["calls"] if c.get("workspace_id") == str(own)
                                and c["operation"] in ("vector_search", "sparse_search")]
                    assert {c["operation"] for c in searches} == {"vector_search", "sparse_search"}
                    assert all(c["chunk_ids"] == [samples[0]["chunk_id"]] for c in searches)
                    data["checks"]["normal_cross_workspace_filter"] = True

                    # Test index IDs as untrusted candidates: only our owned collection is changed.
                    await resources.store._client.set_payload(collection_name=data["collection"],
                        payload={"workspace_id": str(own)}, points=[samples[1]["vector_id"]], wait=True)
                    before = len(data["calls"])
                    response, provider = await request(own, "wrong_vector_workspace_label")
                    assert response.status_code == 200
                    candidates = [c for c in data["calls"][before:] if c["operation"] == "vector_search"]
                    assert any(samples[1]["chunk_id"] in c["chunk_ids"] for c in candidates)
                    data["checks"]["pg_hydration_blocks_foreign_candidate"] = verify_model_visibility(
                        provider.requests, *samples)

                    before = len(data["calls"])
                    response, provider = await request(other, "unauthorized_api")
                    assert response.status_code == 403
                    assert response.json()["error"]["code"] == "permission_denied"
                    assert not provider.requests and data["api_runs"]["unauthorized_api"]["provider_factory_calls"] == 0
                    assert len(data["calls"]) == before
                    data["checks"]["unauthorized_api_denied_before_provider_and_retrieval"] = True

                    result = await create_search_knowledge_tool(db, organization_id=org, user_id=user,
                                                               workspace_id=other).ainvoke({"query": QUERY})
                    data["unauthorized_tool_result"] = result
                    assert result["status"] == "permission_denied" and result["sources"] == []
                    assert len(data["calls"]) == before
                    data["checks"]["tool_rechecks_permission_before_retrieval"] = True
        assert not data.get("observer_errors")
        assert not any(c["operation"] == "chat_provider_factory" for c in data["calls"])
    finally:
        sys.setprofile(None)


async def child(path):
    evidence = Evidence(path)
    data, started = evidence.data, time.monotonic()
    evidence.save()
    resources = Scenario()  # Reuse only isolated dependency ownership/cleanup, never the C05 runner.
    try:
        data["stage"] = "preflight"
        await resources.preflight(data, evidence.save)
        data.pop("expected", None)  # C10 has permission assertions, not the C05 timing fixture.
        async with base.Day8PostgresTests().database("models") as (conn, org, order, helper, _):
            data["schema"] = await conn.scalar(text("SELECT current_schema()"))
            data["pg_backend_pid"] = await conn.scalar(text("SELECT pg_backend_pid()"))
            evidence.save()
            try:
                await asyncio.wait_for(exercise(conn, org, order, helper, resources, evidence), timeout=360)
                data["passed"] = True
            except Exception as exc:  # noqa: BLE001 -- preserve verification failure before rollback
                data.update(passed=False, failure_type=type(exc).__name__, failure_message=str(exc)[:400])
                evidence.save()
        data["rollback_verified"] = True
    except Exception as exc:  # noqa: BLE001 -- structural setup/rollback failure
        data.update(passed=False, setup_or_cleanup_failure=type(exc).__name__)
    finally:
        try:
            await resources.close(data)
        except Exception as exc:  # noqa: BLE001 -- cleanup failure must prevent a pass
            data.update(passed=False, cleanup_failure=type(exc).__name__)
        data["elapsed_seconds"] = round(time.monotonic() - started, 3)
        evidence.save()
    return 0 if data["passed"] and data["rollback_verified"] else 1


async def recheck(data):
    try:
        await base.check_cleanup(data)
    finally:
        await Scenario().cleanup_after_exit(data)
    redis_url = urlsplit(base.settings.REDIS_URL)
    auth = redis_url.netloc.rpartition("@")[0] + "@" if "@" in redis_url.netloc else ""
    original = base.settings.REDIS_URL
    base.settings.REDIS_URL = urlunsplit(redis_url._replace(netloc=auth + "localhost:6380"))
    client = get_redis_client()
    try:
        data["redis_keys_absent"] = {"bm25:version:" + w: not bool(await client.exists("bm25:version:" + w))
                                    for w in data.get("workspaces", {}).values()}
    finally:
        await client.aclose()
        get_redis_client.cache_clear()
        base.settings.REDIS_URL = original


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", type=Path)
    args = parser.parse_args()
    if args.child:
        return asyncio.run(child(args.child))
    started = time.monotonic()
    path = base.ROOT / "scripts" / ("investigation_api_c10_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    print(f"EVIDENCE={path}", flush=True)
    with path.with_suffix(".log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, __file__, "--child", str(path)], stdout=log, stderr=log)
        timing = base.wait_for_child_deadline(process, timeout=420)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"passed": False}
    data.update(timing, process_exit_code=process.returncode, process_exited=process.poll() is not None)
    try:
        asyncio.run(asyncio.wait_for(recheck(data), timeout=20))
    except Exception as exc:  # noqa: BLE001 -- preserve evidence if independent cleanup check fails
        data.update(passed=False, recheck_failure=type(exc).__name__)
    data["passed"] = bool(data.get("passed") and data.get("rollback_verified")
                          and data.get("schema_absent_after_exit") and data.get("pg_session_absent_after_exit")
                          and data.get("collection_absent") and all(data.get("redis_keys_absent", {}).values())
                          and process.returncode == 0 and not timing["outer_timeout"])
    data["total_elapsed_seconds"] = round(time.monotonic() - started, 3)
    data["source_sha256"] = {p: hashlib.sha256((base.ROOT / p).read_bytes()).hexdigest() for p in (
        "scripts/investigation_api_c10_once.py", "scripts/knowledge_retrieval_verify.py",
        "backend/app/api/v1/endpoints/investigations.py", "backend/app/ai/agents/core_agent.py",
        "backend/app/ai/tools/knowledge_tool.py", "backend/app/ai/graph/nodes.py")}
    base.save(path, data)
    print(json.dumps({k: data.get(k) for k in ("passed", "checks", "stage", "failure_type",
                     "setup_or_cleanup_failure", "total_elapsed_seconds", "rollback_verified")}), flush=True)
    return 0 if data["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
