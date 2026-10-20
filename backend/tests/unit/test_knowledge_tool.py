"""Offline Tool/authorization/SQL-scope boundaries; no global DB fixtures."""

import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from app.ai.graph.rag_graph import run_retrieval
from app.ai.reranking.base import RerankResult
from app.ai.retrieval.hybrid_retriever import RetrievedChunk
from app.ai.tools import knowledge_tool as subject
from app.core.exceptions import UpstreamProviderError
from app.db import base as _models  # noqa: F401 -- register ORM relationships, no engine/DDL
from pydantic import ValidationError
from sqlalchemy.dialects import sqlite
from sqlalchemy.ext.asyncio import AsyncSession


def scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


class KnowledgeToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.org, self.user, self.workspace = uuid4(), uuid4(), uuid4()
        self.db = MagicMock(spec=AsyncSession)
        self.db.get.return_value = SimpleNamespace(id=self.workspace, organization_id=self.org)
        self.authorize()
        self.tool = subject.create_search_knowledge_tool(
            self.db, organization_id=self.org, user_id=self.user, workspace_id=self.workspace,
        )
        self.retrieval = self.enterContext(patch.object(subject, "run_retrieval", new_callable=AsyncMock))
        self.source = {"chunk_id": uuid4(), "document_id": uuid4(),
                       "document_filename": "库存差额核查 SOP.pdf", "content": "先核对盘点与预留记录。",
                       "page_number": None, "relevance_score": 0.8}
        self.retrieval.return_value = ("query", [self.source])

    def authorize(self, org_role="member", workspace_role="viewer"):
        self.db.execute.side_effect = [
            scalar_result(SimpleNamespace(role=org_role) if org_role else None),
            scalar_result(SimpleNamespace(role=workspace_role) if workspace_role else None),
        ]

    async def test_legal_call_binds_scope_and_serializes_existing_provenance(self):
        self.source["storage_path"] = "private-do-not-return"
        result = await self.tool.ainvoke({"query": "  库存差额如何核实？  "})
        self.assertEqual(self.tool.name, "search_knowledge")
        self.retrieval.assert_awaited_once_with(
            self.db, workspace_id=self.workspace, history=[], user_message="库存差额如何核实？",
        )
        self.assertEqual(result["status"], "found")
        self.assertIsNone(result["error_code"])
        self.assertEqual(result["sources"], [{
            **{k: v for k, v in self.source.items() if k != "storage_path"},
            "chunk_id": str(self.source["chunk_id"]), "document_id": str(self.source["document_id"]),
        }])
        self.assertNotIn("private-do-not-return", json.dumps(result))
        self.assertIn("not verified business facts", result["message"])
        # Exercise real require_role/require_workspace_role against a DB substitute.
        org_query, workspace_query = [c.args[0].compile().params for c in self.db.execute.await_args_list]
        self.assertEqual(set(org_query.values()), {self.org, self.user})
        self.assertEqual(set(workspace_query.values()), {self.workspace, self.user})
        self.db.commit.assert_not_awaited()
        self.db.add.assert_not_called()

    async def test_only_query_is_model_editable_and_invalid_input_never_executes(self):
        schema = self.tool.get_input_schema().model_json_schema()
        self.assertEqual(set(schema["properties"]), {"query"})
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(self.tool.tool_call_schema.model_json_schema()["properties"]), {"query"})
        variants = [{}, *({"query": q} for q in ("", " \n\t", None, 123))]
        variants += [{"query": "规则？", k: str(uuid4())} for k in (
            "organization_id", "user_id", "workspace_id", "document_ids", "allowed_scope", "db",
        )]
        for arguments in variants:
            with self.subTest(arguments=arguments), self.assertRaises(ValidationError):
                await self.tool.ainvoke(arguments)
        self.retrieval.assert_not_awaited()
        self.db.execute.assert_not_awaited()
        self.db.get.assert_not_awaited()

    async def test_org_membership_does_not_grant_workspace_access(self):
        for role in (None, "invalid-role"):
            self.authorize(workspace_role=role)
            with self.subTest(role=role):
                result = await self.tool.ainvoke({"query": "规则？"})
                self.assertEqual(result["status"], "permission_denied")
                self.assertEqual(result["error_code"], "permission_denied")
                self.assertEqual(result["sources"], [])
        self.retrieval.assert_not_awaited()

    async def test_no_org_membership_denies_before_workspace_or_retrieval(self):
        self.authorize(org_role=None)
        result = await self.tool.ainvoke({"query": "规则？"})
        self.assertEqual(result["status"], "permission_denied")
        self.db.get.assert_not_awaited()
        self.retrieval.assert_not_awaited()

    async def test_foreign_or_missing_workspace_is_denied_not_no_matches(self):
        for workspace in (None, SimpleNamespace(organization_id=uuid4())):
            self.authorize()
            self.db.get.return_value = workspace
            result = await self.tool.ainvoke({"query": "规则？"})
            self.assertEqual(result["status"], "permission_denied")
        self.retrieval.assert_not_awaited()

    async def test_permissions_are_rechecked_on_each_invocation(self):
        await self.tool.ainvoke({"query": "规则？"})
        self.authorize(workspace_role=None)
        result = await self.tool.ainvoke({"query": "再次查规则？"})
        self.assertEqual(result["status"], "permission_denied")
        self.assertEqual(self.retrieval.await_count, 1)

    async def test_no_results_are_distinct_from_denial_and_failure(self):
        self.retrieval.return_value = ("规则？", [])
        result = await self.tool.ainvoke({"query": "规则？"})
        self.assertEqual(result["status"], "no_matches")
        self.assertIsNone(result["error_code"])
        self.assertEqual(result["sources"], [])

    async def test_retrieval_failures_propagate_without_empty_success(self):
        for error in (TimeoutError("timeout"), ConnectionError("offline"),
                      UpstreamProviderError("retrieval failed")):
            self.authorize()
            self.retrieval.side_effect = error
            with self.subTest(error=type(error)), self.assertRaises(type(error)) as caught:
                await self.tool.ainvoke({"query": "规则？"})
            self.assertIs(caught.exception, error)

    async def test_membership_database_failure_is_not_no_matches_or_permission_denial(self):
        error = RuntimeError("database unavailable")
        self.db.execute.side_effect = error
        with self.assertRaises(RuntimeError) as caught:
            await self.tool.ainvoke({"query": "规则？"})
        self.assertIs(caught.exception, error)
        self.retrieval.assert_not_awaited()

    async def test_missing_or_invalid_provenance_is_a_failure_not_fabricated(self):
        for changes in ({"chunk_id": None}, {"document_id": "invented"},
                        {"document_filename": ""}, {"relevance_score": float("nan")}):
            self.authorize()
            self.retrieval.return_value = ("query", [{**self.source, **changes}])
            with self.subTest(changes=changes), self.assertRaises(UpstreamProviderError):
                await self.tool.ainvoke({"query": "规则？"})


class KnowledgeRetrievalScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_excludes_foreign_and_inconsistent_chunks_before_reranking(self):
        # Execute the actual hydration SELECT against minimal in-memory rows;
        # this is SQL-scope verification, not a PostgreSQL integration test.
        workspace, other = uuid4(), uuid4()
        own_doc, foreign_doc = uuid4(), uuid4()
        ids = [uuid4() for _ in range(6)]
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE documents (id TEXT, workspace_id TEXT, original_filename TEXT)")
        connection.execute("""CREATE TABLE document_chunks (
            id TEXT, document_id TEXT, workspace_id TEXT, chunk_index INTEGER,
            content TEXT, token_count INTEGER, vector_id TEXT, page_number INTEGER,
            metadata TEXT, created_at TEXT)""")
        connection.executemany("INSERT INTO documents VALUES (?, ?, ?)", [
            (own_doc.hex, workspace.hex, "SOP.pdf"), (foreign_doc.hex, other.hex, "private.pdf"),
        ])
        for index, (doc, scope, content) in enumerate((
            (own_doc, workspace, "Allowed SOP"), (foreign_doc, other, "Foreign secret"),
            (own_doc, other, "Inconsistent chunk"), (foreign_doc, workspace, "Inconsistent document"),
            (own_doc, workspace, "Not a candidate"),
        )):
            connection.execute("INSERT INTO document_chunks VALUES (?, ?, ?, ?, ?, 1, ?, 2, '{}', NULL)",
                               (ids[index].hex, doc.hex, scope.hex, index, content, uuid4().hex))

        async def execute(statement):
            compiled = statement.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True})
            rows = connection.execute(str(compiled)).fetchall()
            result = MagicMock()
            result.all.return_value = [(SimpleNamespace(
                id=UUID(row["id"]), document_id=UUID(row["document_id"]),
                content=row["content"], page_number=row["page_number"],
            ), row["original_filename"]) for row in rows]
            return result

        db = MagicMock(spec=AsyncSession)
        db.execute.side_effect = execute
        reranker = SimpleNamespace(rerank=AsyncMock(return_value=[RerankResult(index=0, relevance_score=0.9)]))
        candidates = [RetrievedChunk(chunk_id=i, fused_score=0.5) for i in ids[:4] + ids[5:]]
        with (patch("app.ai.graph.nodes.hybrid_retrieve", new_callable=AsyncMock,
                    return_value=candidates) as retrieve,
              patch("app.ai.graph.nodes.get_rerank_provider", return_value=reranker),
              patch("app.ai.graph.nodes.get_llm_provider") as llm):
            query, chunks = await run_retrieval(db, workspace_id=workspace, history=[], user_message="SOP?")
        self.assertEqual(query, "SOP?")
        self.assertEqual(retrieve.await_args.kwargs["workspace_id"], workspace)
        self.assertEqual(reranker.rerank.await_args.kwargs["documents"], ["Allowed SOP"])
        self.assertEqual(chunks, [{"chunk_id": str(ids[0]), "document_id": str(own_doc),
                                  "document_filename": "SOP.pdf", "content": "Allowed SOP",
                                  "page_number": 2, "relevance_score": 0.9}])
        llm.assert_not_called()
