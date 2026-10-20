"""Fixed C05 fixture/contract for the existing authenticated single-run API runner.

No Agent branches or prompt changes. Shipment is one hour late, delivery one hour
early, on one tracking number. The SOP is a reference, never a business cause.
"""

import json
from datetime import timedelta
from pathlib import PureWindowsPath
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
from app.ai.agents.investigation_report import validate_report
from app.ai.embeddings.factory import get_embedding_provider
from app.ai.vectorstore.factory import get_vector_store
from app.core.config import settings
from app.core.redis_client import get_redis_client
from app.db.base import Base
from app.models.exception_case import ExceptionCase
from app.models.fulfillment_event import FulfillmentEvent
from app.models.workspace import WorkspaceMember
from knowledge_retrieval_verify import cleanup_collection, index_samples, seed_reference
from qdrant_client import AsyncQdrantClient
from sqlalchemy import insert

QUESTION = (
    "Review shipment timing and consult the authorized Shipment delay review SOP "
    "for handling rules. Record business evidence and the applicable rule source separately. "
    "The cause remains unconfirmed."
)
SOP_NAME = "Shipment-delay-review-SOP.txt"
SOP_TEXT = (
    "Shipment delay review SOP: compare the promised and actual shipment times for the "
    "same tracking number. Preserve event references and obtain missing causal evidence "
    "before proposing a cause. This procedure does not establish facts about any order, "
    "authorize notification or assignment, or prove that a proposed action was executed."
)


def business_fixture(org, order, helper, observed):
    case = helper.case(org, order)
    case.update(exception_type="other", opened_at=observed, problem_description=QUESTION)
    rows = []
    for kind, hours, deadline in (
        ("shipment_promised", -6, -4), ("delivery_promised", -6, -1),
        ("shipped", -3, None), ("delivered", -2, None),
    ):
        rows.append(helper.event(
            org, order, event_type=kind, tracking_number="RULE-REVIEW-SHIPMENT",
            occurred_at=observed + timedelta(hours=hours),
            expected_at=observed + timedelta(hours=deadline) if deadline is not None else None,
            description="Recorded fulfillment timing; cause unconfirmed."))
    return case, rows


class Scenario:
    def __init__(self):
        self.original_collection = settings.QDRANT_COLLECTION_NAME
        self.original_redis = settings.REDIS_URL
        self.store = self.embedding = self.redis = None

    async def preflight(self, data, checkpoint):
        # Only this runner process changes settings; no environment/config files.
        redis_url = urlsplit(self.original_redis)
        auth = redis_url.netloc.rpartition("@")[0] + "@" if "@" in redis_url.netloc else ""
        settings.REDIS_URL = urlunsplit(redis_url._replace(netloc=auth + "localhost:6380"))
        assert get_vector_store.cache_info().currsize == 0
        assert get_redis_client.cache_info().currsize == 0
        assert settings.EMBEDDING_PROVIDER == "ollama"
        assert settings.EMBEDDING_MODEL == "nomic-embed-text" and settings.EMBEDDING_DIMENSIONS == 768
        data.update(collection="project_a_knowledge_test_" + uuid4().hex,
                    collection_owned=False, original_collection=self.original_collection,
                    redis_endpoint={"host": "localhost", "port": 6380},
                    expected={"outcome": "observed_delay", "root_cause": "unknown",
                              "shipment_difference_seconds": 3600, "delivery_difference_seconds": -3600})
        checkpoint()
        settings.QDRANT_COLLECTION_NAME = data["collection"]
        self.store, self.embedding, self.redis = get_vector_store(), get_embedding_provider(), get_redis_client()
        assert not await self.store._client.collection_exists(data["collection"])
        # Persist ownership before creation so a killed child can be cleaned by its parent.
        data["collection_owned"] = True
        checkpoint()
        from investigation_api_c03_once import check_cleanup
        await check_cleanup({})  # Existing URL + actual database identity protection; read-only.
        assert await self.redis.ping()
        async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL, timeout=15) as client:
            sources = {}
            for model in ("llama3.1:8b", "nomic-embed-text"):
                response = await client.post("/api/show", json={"model": model})
                response.raise_for_status()
                source = next(line[5:] for line in response.json()["modelfile"].splitlines()
                              if line.startswith("FROM "))
                assert PureWindowsPath(source).is_relative_to(PureWindowsPath("D:/OllamaModels"))
                sources[model] = source
        data["preflight"] = {"pg_identity": True, "redis_ping": True,
                             "qdrant_reachable": True, "model_sources": sources}
        checkpoint()

    async def seed(self, conn, org, order, helper, data):
        from day13_e2e import OBSERVED
        case, rows = business_fixture(org, order, helper, OBSERVED)
        await conn.execute(insert(ExceptionCase).values(**case))
        identifiers = []
        for row in rows:
            row.setdefault("id", uuid4())
            identifiers.append(str(row["id"]))
            await conn.execute(insert(FulfillmentEvent).values(**row))
        data["fixture_event_ids"] = identifiers
        data["fixture_question"] = QUESTION
        data["fixture_times"] = {row["event_type"]: {
            "occurred_at": row["occurred_at"].isoformat(),
            "expected_at": row["expected_at"].isoformat() if row["expected_at"] else None,
        } for row in rows}
        return case["id"]

    async def prepare(self, conn, org, user_id, data, checkpoint):
        for name in ("workspaces", "workspace_members", "documents", "document_chunks"):
            await conn.run_sync(Base.metadata.tables[name].create)
        workspace = uuid4()
        await conn.execute(insert(Base.metadata.tables["workspaces"]).values(
            id=workspace, organization_id=org, name="Isolated shipment rules", slug=uuid4().hex))
        await conn.execute(insert(WorkspaceMember).values(
            id=uuid4(), workspace_id=workspace, user_id=user_id, role="viewer"))
        data.update(workspace_id=str(workspace), knowledge_user_id=str(user_id))
        data["sample"] = await seed_reference(conn, workspace=workspace, user=user_id,
                                               filename=SOP_NAME, content=SOP_TEXT)
        checkpoint()
        await self.store.ensure_collection()
        data["indexed_chunk_ids"] = await index_samples(self.embedding, self.store, [data["sample"]])
        data["preflight"]["embedding_dimensions"] = settings.EMBEDDING_DIMENSIONS
        checkpoint()  # All real dependency checks/indexing precede the first chat request.

    def verify(self, data):
        trace, report, answer = data["trace"], data["report"], data["answer"]
        path = [step["tool"] for step in trace if step["result"]["status"] != "invalid_input"]
        assert sum(step["result"]["status"] == "invalid_input" for step in trace) <= 1
        assert path == ["get_exception_case", "analyze_fulfillment", "search_knowledge"]
        assert report["outcome"] == "observed_delay" and report["root_cause"] == "unknown"
        assert len(report["evidence_event_ids"]) == 4
        assert set(report["evidence_event_ids"]) == set(data["fixture_event_ids"])
        sample = data["sample"]
        assert report["knowledge_source_ids"] == [sample["chunk_id"]]
        assert sample["chunk_id"] not in report["evidence_event_ids"]
        analysis = next(s["result"]["analysis"] for s in trace if s["tool"] == "analyze_fulfillment")
        for kind, status, difference in (("shipment", "late", 3600), ("delivery", "on_time", -3600)):
            assert analysis[kind]["status"] == status
            assert analysis[kind]["difference_seconds"] == difference
            assert analysis[kind]["expected_at"] and analysis[kind]["actual_at"]
        assert analysis["whole_order_completion"] == "unknown"
        result = next(s["result"] for s in trace if s["tool"] == "search_knowledge")
        assert result["status"] == "found" and len(result["sources"]) == 1
        for field in ("chunk_id", "document_id", "document_filename", "content"):
            assert result["sources"][0][field] == sample[field]
        validate_report(json.dumps(report), trace)
        for identifier in [*data["fixture_event_ids"], sample["chunk_id"], sample["document_id"]]:
            assert identifier in answer
        assert sample["document_filename"] in answer
        assert sample["content"] not in answer.split("2. 证据引用及观察时间")[0]
        assert "知识参考（非业务事实）" in answer and "未验证片段是否支持建议" in answer
        assert data["agent_input"]["workspace_id"] == data["workspace_id"]
        assert data["agent_input"]["user_id"] == data["knowledge_user_id"] == data["authenticated_user_id"]
        assert data["verified_workspace_membership"] == {
            "workspace_id": data["workspace_id"], "user_id": data["knowledge_user_id"], "role": "viewer"}
        assert data["model_requests"] == len(data["requests"])
        assert not data.get("observer_errors")
        data["tool_path"] = path

    async def close(self, data):
        try:
            if self.store:
                data["collection_absent"] = await cleanup_collection(
                    self.store._client, data["collection"], self.original_collection,
                    data.get("collection_owned", False))
                assert data["collection_absent"]
        finally:
            settings.QDRANT_COLLECTION_NAME = self.original_collection
            settings.REDIS_URL = self.original_redis
            errors = []
            for resource in (self.store._client if self.store else None,
                             self.embedding._client if self.embedding else None, self.redis):
                if resource is not None:
                    try:
                        await (resource.aclose() if hasattr(resource, "aclose") else resource.close())
                    except Exception as exc:  # noqa: BLE001 -- finish closing all clients
                        errors.append(type(exc).__name__)
            get_vector_store.cache_clear()
            get_embedding_provider.cache_clear()
            get_redis_client.cache_clear()
            if errors:
                raise RuntimeError("Knowledge clients did not all close")

    async def cleanup_after_exit(self, data):
        if not data.get("collection"):
            data["collection_absent"] = True
            return
        # Parent only touches this child's persisted UUID, never the normal collection.
        assert data["original_collection"] == settings.QDRANT_COLLECTION_NAME
        client = AsyncQdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)
        try:
            data["collection_absent"] = await cleanup_collection(
                client, data["collection"], settings.QDRANT_COLLECTION_NAME,
                data.get("collection_owned", False))
        finally:
            await client.close()
