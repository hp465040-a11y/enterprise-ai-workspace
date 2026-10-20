"""Real search_knowledge verification in guarded PG and a private Qdrant collection.

No mocks, chat generation, business migrations or writes to the normal collection.
Only process-local Qdrant collection configuration is overridden. Embedding and
reranking configuration are inherited unchanged. Redis version keys are read only.
"""

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

# Audited bootstrap pins PG to ragforge_day6_test before app settings are loaded.
from day11_e2e import ROOT, settings
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from test_day6_postgres import Day6PostgresTests

BOOTSTRAP_ROOT = ROOT

from app.ai.embeddings.factory import get_embedding_provider
from app.ai.llm.factory import get_llm_provider
from app.ai.retrieval.bm25_index import sparse_search
from app.ai.tools.knowledge_tool import create_search_knowledge_tool
from app.ai.vectorstore.base import VectorPoint
from app.ai.vectorstore.factory import get_vector_store
from app.core.redis_client import get_redis_client
from app.core.security import hash_password
from app.db.base import Base
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.models.organization import OrganizationMember
from app.models.workspace import WorkspaceMember


class Evidence:
    def __init__(self):
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        self.path = ROOT / "scripts" / f"knowledge_retrieval_{stamp}.json"
        self.data = {"passed": False, "pid": os.getpid(), "started_at": stamp,
                     "database": "ragforge_day6_test", "checks": {}, "calls": [],
                     "rollback_verified": False, "collection_absent": None}
        self.save()
        print(f"EVIDENCE={self.path}", flush=True)

    def save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def event(self, name, **values):
        with self.path.with_suffix(".jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": datetime.now(UTC).isoformat(), "event": name,
                                     **values}, ensure_ascii=False) + "\n")


class Observer:
    """Profile original functions; no replacement providers or queries."""

    def __init__(self, evidence, embedding, store):
        self.evidence = evidence
        self.frames = {}
        self.targets = {type(embedding).embed_documents.__code__: "embed_documents",
                        type(embedding).embed_query.__code__: "embed_query",
                        type(store).search.__code__: "vector_search",
                        sparse_search.__code__: "sparse_search",
                        get_llm_provider.__wrapped__.__code__: "chat_provider_factory"}

    def __call__(self, frame, action, value):
        if action not in ("call", "return") or frame.f_code not in self.targets:
            return
        try:
            if frame not in self.frames:
                entry = {"operation": self.targets[frame.f_code]}
                if "workspace_id" in frame.f_locals:
                    entry["workspace_id"] = str(frame.f_locals["workspace_id"])
                self.frames[frame] = (time.monotonic(), entry)
                self.evidence.data["calls"].append(entry)
                self.evidence.event("call_started", **entry)
            started, entry = self.frames[frame]
            # Async functions also emit return events at suspension; only record
            # their concrete final result, never a Future or vector contents.
            if action == "return" and (isinstance(value, list) or hasattr(value, "vectors")):
                entry["elapsed_seconds"] = round(time.monotonic() - started, 3)
                if entry["operation"] == "embed_documents":
                    entry["vectors"] = len(value.vectors)
                    entry["dimensions"] = [len(vector) for vector in value.vectors]
                elif entry["operation"] == "embed_query":
                    entry["dimensions"] = len(value)
                elif entry["operation"] == "vector_search":
                    entry["chunk_ids"] = [row.payload["chunk_id"] for row in value]
                elif entry["operation"] == "sparse_search":
                    entry["chunk_ids"] = [str(row.chunk_id) for row in value]
                self.evidence.event("call_completed", **entry)
        except Exception as exc:  # noqa: BLE001 -- never alter the observed execution
            self.evidence.data.setdefault("observer_errors", []).append(type(exc).__name__)


async def seed_reference(conn, *, workspace, user, filename, content):
    """Shared synthetic document/chunk fixture; no ingestion or business writes."""
    document, chunk, vector = uuid4(), uuid4(), uuid4()
    await conn.execute(insert(Document).values(
        id=document, workspace_id=workspace, uploaded_by=user,
        filename=filename, original_filename=filename, mime_type="text/plain",
        size_bytes=len(content.encode()), storage_path=f"isolated-verification/{document}",
        status="completed"))
    await conn.execute(insert(DocumentChunk).values(
        id=chunk, document_id=document, workspace_id=workspace, chunk_index=0,
        content=content, token_count=len(content.split()), vector_id=vector, page_number=1))
    return {"workspace_id": str(workspace), "document_id": str(document),
            "chunk_id": str(chunk), "vector_id": str(vector),
            "document_filename": filename, "content": content}


async def index_samples(embedding, store, samples, *, before_upsert=None):
    vectors = await embedding.embed_documents([sample["content"] for sample in samples])
    assert len(vectors.vectors) == len(samples)
    assert all(len(v) == settings.EMBEDDING_DIMENSIONS for v in vectors.vectors)
    if before_upsert:
        before_upsert()
    await store.upsert([VectorPoint(id=UUID(sample["vector_id"]), vector=vector, payload={
        key: sample[key] for key in ("workspace_id", "document_id", "chunk_id")})
        for sample, vector in zip(samples, vectors.vectors, strict=True)])
    points, _ = await store._client.scroll(collection_name=store._collection, limit=10, with_vectors=False)
    assert {str(point.id) for point in points} == {sample["vector_id"] for sample in samples}
    return [point.payload["chunk_id"] for point in points]


async def cleanup_collection(client, collection, original, owned):
    """Delete only a UUID-named, explicitly owned test collection."""
    assert collection.startswith("project_a_knowledge_test_") and collection != original
    assert UUID(hex=collection.removeprefix("project_a_knowledge_test_")).hex == collection.removeprefix("project_a_knowledge_test_")
    exists = await client.collection_exists(collection)
    if owned and exists:
        await client.delete_collection(collection_name=collection)
    return not await client.collection_exists(collection)


async def seed(conn, org):
    for name in ("users", "organization_members", "workspaces", "workspace_members", "documents", "document_chunks"):
        await conn.run_sync(Base.metadata.tables[name].create)
    user, other_user = uuid4(), uuid4()
    own, other, empty = uuid4(), uuid4(), uuid4()
    for identifier in (user, other_user):
        await conn.execute(insert(Base.metadata.tables["users"]).values(
            id=identifier, email=f"knowledge-{identifier}@example.invalid",
            hashed_password=hash_password(uuid4().hex), full_name="Isolated knowledge user", is_active=True))
        await conn.execute(insert(OrganizationMember).values(
            id=uuid4(), organization_id=org, user_id=identifier, role="member"))
    for workspace, owner in ((own, user), (other, other_user), (empty, user)):
        await conn.execute(insert(Base.metadata.tables["workspaces"]).values(
            id=workspace, organization_id=org, name="Isolated SOP workspace", slug=uuid4().hex))
        await conn.execute(insert(WorkspaceMember).values(
            id=uuid4(), workspace_id=workspace, user_id=owner, role="viewer"))
    samples = []
    for workspace, filename, content in (
        (own, "Allowed-inventory-SOP.txt", "Inventory discrepancy SOP ALLOWED-A: compare stock count and reservation ledger before any order shortage conclusion."),
        (other, "Restricted-inventory-SOP.txt", "Inventory discrepancy SOP RESTRICTED-B: compare stock count and reservation ledger before any order shortage conclusion."),
    ):
        samples.append(await seed_reference(conn, workspace=workspace,
            user=user if workspace == own else other_user, filename=filename, content=content))
    return user, own, other, empty, samples


async def exercise(conn, org, evidence, embedding, store):
    evidence.data["stage"] = "seed"
    user, own, other, empty, samples = await seed(conn, org)
    evidence.data.update(user_id=str(user), organization_id=str(org), workspaces={
        "authorized": str(own), "unauthorized": str(other), "empty_authorized": str(empty)}, samples=samples)
    # Preserve the actual membership records used by the real Tool's Service checks.
    members = (await conn.execute(select(WorkspaceMember.workspace_id, WorkspaceMember.user_id,
                                        WorkspaceMember.role))).all()
    evidence.data["memberships"] = [{"workspace_id": str(row.workspace_id),
                                    "user_id": str(row.user_id), "role": row.role} for row in members]
    observer = Observer(evidence, embedding, store)
    sys.setprofile(observer)
    try:
        evidence.data["stage"] = "index_embedding"
        evidence.data["indexed_chunk_ids"] = await index_samples(
            embedding, store, samples,
            before_upsert=lambda: evidence.data.update(stage="index_upsert"))
        await conn.execute(text("SET LOCAL transaction_read_only = on"))
        async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint") as db:
            query = "Inventory discrepancy SOP: how to check stock count and reservation ledger?"
            evidence.data["query"] = query

            async def invoke(workspace, label):
                evidence.data["stage"] = label
                result = await create_search_knowledge_tool(
                    db, organization_id=org, user_id=user, workspace_id=workspace,
                ).ainvoke({"query": query})
                evidence.data.setdefault("results", {})[label] = result
                evidence.event("tool_returned", label=label, result=result)
                evidence.save()
                return result

            allowed = await invoke(own, "authorized")
            assert allowed["status"] == "found"
            assert len(allowed["sources"]) == 1
            for field in ("chunk_id", "document_id", "document_filename", "content"):
                assert allowed["sources"][0][field] == samples[0][field]
            evidence.data["checks"]["authorized_source_matches_pg"] = True
            assert samples[1]["chunk_id"] not in json.dumps(allowed)
            assert samples[1]["document_id"] not in json.dumps(allowed)
            assert "RESTRICTED-B" not in json.dumps(allowed)
            own_searches = [c for c in evidence.data["calls"] if c.get("workspace_id") == str(own)]
            assert {c["operation"] for c in own_searches} == {"vector_search", "sparse_search"}
            assert all(c["chunk_ids"] == [samples[0]["chunk_id"]] for c in own_searches)
            evidence.data["checks"]["foreign_similar_document_excluded"] = True

            before = len(evidence.data["calls"])
            denied = await invoke(other, "unauthorized")
            assert denied["status"] == "permission_denied" and denied["sources"] == []
            assert len(evidence.data["calls"]) == before
            evidence.data["checks"]["denied_before_embedding_or_search"] = True

            no_matches = await invoke(empty, "empty_authorized")
            assert no_matches["status"] == "no_matches" and no_matches["sources"] == []
            evidence.data["checks"]["empty_workspace_no_matches"] = True
        assert not any(c["operation"] == "chat_provider_factory" for c in evidence.data["calls"])
        assert not evidence.data.get("observer_errors")
        evidence.data["stage"] = "verified"
    finally:
        sys.setprofile(None)


async def main():
    evidence = Evidence()
    started = time.monotonic()
    original_collection = settings.QDRANT_COLLECTION_NAME
    collection = "project_a_knowledge_test_" + uuid4().hex
    evidence.data["collection"] = collection
    evidence.data["configuration"] = {key: getattr(settings, key) for key in (
        "EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS", "RERANK_PROVIDER", "RERANK_MODEL")}
    assert collection != original_collection
    assert get_vector_store.cache_info().currsize == 0
    settings.QDRANT_COLLECTION_NAME = collection  # Private process only, not a config file/model change.
    store, embedding = get_vector_store(), get_embedding_provider()
    owns_collection = False
    try:
        assert store._collection == collection
        assert not await store._client.collection_exists(collection)
        async with Day6PostgresTests().database("models") as (conn, org, _):
            evidence.data["schema"] = await conn.scalar(text("SELECT current_schema()"))
            evidence.data["pg_backend_pid"] = await conn.scalar(text("SELECT pg_backend_pid()"))
            evidence.save()
            try:
                # UUID collection was absent; retain ownership even on partial setup failure.
                owns_collection = True
                evidence.event("isolated_resources", schema=evidence.data["schema"], collection=collection)
                await store.ensure_collection()
                await asyncio.wait_for(exercise(conn, org, evidence, embedding, store), timeout=360)
                evidence.data["passed"] = True
            except Exception as exc:  # noqa: BLE001 -- preserve result, then exit fixture normally for rollback
                evidence.data.update(passed=False, failure_type=type(exc).__name__)
                evidence.event("verification_failed", failure_type=type(exc).__name__)
        evidence.data["rollback_verified"] = True  # Fixture has asserted the schema disappeared.
    except Exception as exc:  # noqa: BLE001 -- structural diagnostics only, never credentials
        evidence.data.update(passed=False, setup_or_cleanup_failure=type(exc).__name__)
    finally:
        try:
            assert store._collection == collection
            evidence.data["collection_absent"] = await cleanup_collection(
                store._client, collection, original_collection, owns_collection)
        except Exception as exc:  # noqa: BLE001 -- do not hide incomplete cleanup
            evidence.data.update(passed=False, collection_cleanup_failure=type(exc).__name__)
        settings.QDRANT_COLLECTION_NAME = original_collection
        await store._client.close()
        if hasattr(embedding, "_client") and hasattr(embedding._client, "aclose"):
            await embedding._client.aclose()
        await get_redis_client().aclose()
        evidence.data["configuration_unchanged"] = all(
            getattr(settings, key) == value for key, value in evidence.data["configuration"].items())
        evidence.data["elapsed_seconds"] = round(time.monotonic() - started, 3)
        evidence.data["passed"] &= evidence.data["rollback_verified"] and evidence.data["collection_absent"] is True
        evidence.event("cleanup_completed", rollback_verified=evidence.data["rollback_verified"],
                       collection_absent=evidence.data["collection_absent"])
        evidence.save()
        print(json.dumps({key: evidence.data.get(key) for key in (
            "passed", "checks", "failure_type", "setup_or_cleanup_failure", "rollback_verified",
            "collection_absent", "elapsed_seconds")}), flush=True)
    return 0 if evidence.data["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
