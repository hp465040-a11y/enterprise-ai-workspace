"""Offline runner tests: real ASGI/JWT/Core/Tools/report, fake external storage/model I/O.

No PostgreSQL, Qdrant, Redis, Embedding or Ollama connections; no global conftest.
The dictionary-backed SQL response double is not a PostgreSQL integration test.
"""

import copy
import json
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import investigation_api_c03_once as runner
import investigation_c05 as c05
import test_day6_postgres as day6
from knowledge_retrieval_verify import cleanup_collection
from sqlalchemy import Insert
from sqlalchemy.sql.elements import TextClause

from app.ai.llm.base import LLMToolCall, LLMToolResponse
from app.core.config import settings


class ControlledProvider:
    def __init__(self, harness):
        self.harness = harness
        self._client = SimpleNamespace(aclose=AsyncMock())
        self.index = 0

    async def generate_with_tools(self, *, messages, tools, system):
        h = self.harness
        self.index += 1
        assert json.loads(messages[0].content)["require_knowledge"] is True
        calls = [
            ("get_exception_case", {"case_id": str(h.rows["exception_cases"][0]["id"])}),
            ("analyze_fulfillment", {"order_id": str(h.order), "as_of": runner.OBSERVED.isoformat()}),
            ("search_knowledge", {"query": "Shipment delay review SOP handling rules"}),
        ]
        if self.index <= len(calls):
            name, args = calls[self.index - 1]
            assert name in {t.name for t in tools}
            return LLMToolResponse("", "controlled", "tool_use", [LLMToolCall(str(uuid4()), name, args)])
        assert tools == []
        report = {"outcome": "observed_delay", "root_cause": "unknown",
                  "evidence_event_ids": [str(r["id"]) for r in h.rows["fulfillment_events"]],
                  "knowledge_source_ids": [str(h.rows["document_chunks"][0]["id"])]}
        if h.bad_report:
            report["root_cause"] = "SOP proves inventory shortage"
        return LLMToolResponse(json.dumps(report), "controlled", "stop")


class C05EntryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.org, self.order = uuid4(), uuid4()
        self.rows = {"orders": [{"id": self.order, "organization_id": self.org}]}
        self.rolled_back = False
        self.bad_report = False
        self.enterContext(patch("socket.socket.connect", side_effect=AssertionError("Offline: network forbidden")))
        self.original_collection, self.original_redis = settings.QDRANT_COLLECTION_NAME, settings.REDIS_URL
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(self.tmp) / "offline.json"
        self.conn = SimpleNamespace(execute=AsyncMock(side_effect=self.execute),
                                    scalar=AsyncMock(side_effect=self.scalar), run_sync=AsyncMock())
        self.db = MagicMock(spec=runner.AsyncSession)
        self.db.execute.side_effect = self.execute
        self.db.get.side_effect = self.get
        self.db.__aenter__.return_value = self.db
        self.enterContext(patch.object(runner, "AsyncSession", return_value=self.db))
        self.enterContext(patch.object(runner.Day8PostgresTests, "database", self.database))
        self.provider = ControlledProvider(self)
        self.enterContext(patch.object(runner, "OllamaProvider", ControlledProvider))
        self.enterContext(patch.object(runner, "get_llm_provider", return_value=self.provider))
        self.enterContext(patch("app.api.v1.endpoints.investigations.get_llm_provider", return_value=self.provider))
        self.enterContext(patch.object(runner, "check_cleanup", new_callable=AsyncMock))
        self.collection_exists = False
        self.client = SimpleNamespace(
            collection_exists=AsyncMock(side_effect=lambda _: self.collection_exists),
            delete_collection=AsyncMock(side_effect=self.delete_collection), close=AsyncMock(),
            scroll=AsyncMock(side_effect=self.scroll))
        self.store = SimpleNamespace(_client=self.client, _collection=None,
                                     ensure_collection=AsyncMock(side_effect=self.ensure_collection), upsert=AsyncMock())
        self.embedding = SimpleNamespace(embed_documents=AsyncMock(return_value=SimpleNamespace(vectors=[[0.1]*768])),
                                         _client=SimpleNamespace(aclose=AsyncMock()))
        self.redis = SimpleNamespace(ping=AsyncMock(return_value=True), aclose=AsyncMock())
        for name, value in (("get_vector_store", self.store), ("get_embedding_provider", self.embedding),
                            ("get_redis_client", self.redis)):
            factory = self.enterContext(patch.object(c05, name, return_value=value))
            factory.cache_info.return_value = SimpleNamespace(currsize=0)
        show = MagicMock()
        show.json.return_value = {"modelfile": "FROM D:\\OllamaModels\\blobs\\fixture"}
        client = MagicMock()
        client.__aenter__.return_value = SimpleNamespace(post=AsyncMock(return_value=show))
        self.enterContext(patch.object(c05.httpx, "AsyncClient", return_value=client))
        self.retrieval = self.enterContext(patch("app.ai.tools.knowledge_tool.run_retrieval",
                                               new_callable=AsyncMock, side_effect=self.retrieve))
        self.extension = c05.Scenario()

    async def execute(self, statement):
        if isinstance(statement, TextClause):
            return None
        if isinstance(statement, Insert):
            values = statement.compile().params
            self.rows.setdefault(statement.table.name, []).append(values)
            return None
        entity = statement.column_descriptions[0]["entity"]
        records = list(self.rows.get(entity.__tablename__, []))
        for condition in statement._where_criteria:
            key, value = condition.left.key, condition.right.value
            records = [r for r in records if condition.operator(r.get(key), value)]
        objects = []
        for record in records:
            values = dict(record)
            if entity.__tablename__ == "exception_cases":
                values.setdefault("status", "open")
                values.setdefault("evidence_event_ids", [])
            objects.append(entity(**values))
        result = MagicMock()
        result.scalar_one_or_none.return_value = objects[0] if objects else None
        result.scalars.return_value.all.return_value = objects
        return result

    async def get(self, entity, identifier):
        row = next(r for r in self.rows[entity.__tablename__] if r["id"] == identifier)
        return entity(**row)

    async def scalar(self, statement):
        return "day6_test_offline" if "current_schema" in str(statement) else 123

    @asynccontextmanager
    async def database(self, mode):
        try:
            yield self.conn, self.org, self.order, day6.Day6PostgresTests(), None
        finally:
            self.rolled_back = True  # Simulated fixture finalizer, not a real rollback claim.

    async def ensure_collection(self):
        self.collection_exists = True
        self.store._collection = settings.QDRANT_COLLECTION_NAME

    async def delete_collection(self, *, collection_name):
        self.assertEqual(collection_name, self.store._collection)
        self.collection_exists = False

    async def scroll(self, **kwargs):
        row = self.rows["document_chunks"][0]
        return [SimpleNamespace(id=row["vector_id"], payload={"chunk_id": str(row["id"])})], None

    async def retrieve(self, db, *, workspace_id, history, user_message):
        chunk, doc = self.rows["document_chunks"][0], self.rows["documents"][0]
        self.assertEqual(workspace_id, chunk["workspace_id"])
        return user_message, [{"chunk_id": str(chunk["id"]), "document_id": str(doc["id"]),
                               "document_filename": doc["filename"], "content": chunk["content"],
                               "page_number": 1, "relevance_score": 1.0}]

    async def run_entry(self):
        result = await runner.child(self.path, self.extension)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(self.rolled_back)
        self.assertFalse(self.collection_exists)
        self.client.delete_collection.assert_awaited_once()
        self.assertEqual(settings.QDRANT_COLLECTION_NAME, self.original_collection)
        self.assertEqual(settings.REDIS_URL, self.original_redis)
        self.assertTrue(data["collection_absent"])
        return result, data

    async def test_complete_entry_controlled_provider_and_fixed_contract(self):
        result, data = await self.run_entry()
        self.assertEqual(result, 0, data)
        self.assertTrue(data["passed"])
        self.assertEqual(data["tool_path"], ["get_exception_case", "analyze_fulfillment", "search_knowledge"])
        self.assertEqual(data["model_requests"], 4)
        self.assertEqual(data["requests"][-1]["offered_tools"], [])
        self.retrieval.assert_awaited_once()
        self.assertEqual(data["fixture_question"], c05.QUESTION)
        self.assertIn('"event": "api_returned"', self.path.with_suffix('.jsonl').read_text(encoding='utf-8'))
        for field, value in (("outcome", "no_observed_delay"), ("root_cause", "inventory shortage"),
                             ("knowledge_source_ids", []), ("knowledge_source_ids", [str(uuid4())]),
                             ("evidence_event_ids", [data["sample"]["chunk_id"]])):
            bad = copy.deepcopy(data)
            bad["report"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises((AssertionError, ValueError)):
                self.extension.verify(bad)
        bad = copy.deepcopy(data)
        bad["trace"] = [step for step in bad["trace"] if step["tool"] != "search_knowledge"]
        with self.assertRaises(AssertionError):
            self.extension.verify(bad)

    async def test_retrieval_failure_keeps_failure_and_runs_cleanup(self):
        self.retrieval.side_effect = ConnectionError("offline retrieval failure")
        result, data = await self.run_entry()
        self.assertEqual(result, 1)
        self.assertEqual(data["error_code"], "tool_failed")
        self.assertNotIn("report", data["api_response"])
        self.assertEqual(self.provider.index, 3)

    async def test_two_bad_reports_fail_and_cleanup(self):
        self.bad_report = True
        result, data = await self.run_entry()
        self.assertEqual(result, 1)
        self.assertEqual(data["error_code"], "ungrounded_final")
        self.assertEqual(self.provider.index, 5)

    async def test_partial_index_failure_cleans_before_any_chat(self):
        self.store.upsert.side_effect = ConnectionError("partial upsert")
        result, data = await self.run_entry()
        self.assertEqual(result, 1)
        self.assertEqual(data["failure_stage"], "knowledge_setup")
        self.assertEqual(self.provider.index, 0)

    async def test_parent_cleans_owned_collection_after_child_interruption(self):
        name = "project_a_knowledge_test_" + uuid4().hex
        self.collection_exists = True
        self.store._collection = name
        data = {"collection": name, "original_collection": self.original_collection, "collection_owned": True}
        with patch.object(c05, "AsyncQdrantClient", return_value=self.client):
            await self.extension.cleanup_after_exit(data)
        self.assertTrue(data["collection_absent"])
        self.client.delete_collection.assert_awaited_once_with(collection_name=name)

    async def test_cleanup_refuses_business_or_unowned_collection(self):
        name = "project_a_knowledge_test_" + uuid4().hex
        self.collection_exists = True
        self.assertFalse(await cleanup_collection(self.client, name, self.original_collection, False))
        self.client.delete_collection.assert_not_awaited()
        for unsafe in (self.original_collection, "project_a_knowledge_test_not-a-uuid"):
            with self.subTest(unsafe=unsafe), self.assertRaises((AssertionError, ValueError)):
                await cleanup_collection(self.client, unsafe, self.original_collection, True)
        self.client.delete_collection.assert_not_awaited()

    async def test_cleanup_failure_never_passes_and_restores_configuration(self):
        self.client.delete_collection.side_effect = ConnectionError("cleanup unavailable")
        result = await runner.child(self.path, self.extension)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(result, 1)
        self.assertFalse(data["passed"])
        self.assertEqual(data["knowledge_cleanup_failure"], "ConnectionError")
        self.assertTrue(self.rolled_back)
        self.assertEqual(settings.QDRANT_COLLECTION_NAME, self.original_collection)
        self.assertEqual(settings.REDIS_URL, self.original_redis)
        self.redis.aclose.assert_awaited_once()
        self.embedding._client.aclose.assert_awaited_once()

    async def test_preflight_failure_stops_before_seed_or_chat(self):
        self.redis.ping.side_effect = ConnectionError("offline unavailable dependency")
        result = await runner.child(self.path, self.extension)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(result, 1)
        self.assertFalse(data["passed"])
        self.assertEqual(self.provider.index, 0)
        self.assertNotIn("exception_cases", self.rows)
        self.client.delete_collection.assert_not_awaited()
        self.assertEqual(settings.REDIS_URL, self.original_redis)

    def test_existing_c03_saved_acceptance_unchanged(self):
        path = runner.ROOT / 'scripts/investigation_api_c03_20261015T133719531091Z.json'
        runner.verify(json.loads(path.read_text(encoding='utf-8')))

    def test_windows_timeout_stops_only_owned_child_tree(self):
        process = MagicMock(pid=12345)
        with (patch.object(runner.os, "name", "nt"),
              patch.object(runner.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as stop):
            runner.stop_child_tree(process)
        stop.assert_called_once_with(
            ["taskkill", "/PID", "12345", "/T", "/F"],
            capture_output=True, timeout=5, check=False,
        )
        process.wait.assert_called_once_with(timeout=5)
        process.kill.assert_not_called()
