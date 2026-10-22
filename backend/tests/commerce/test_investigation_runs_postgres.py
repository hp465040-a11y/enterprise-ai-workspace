"""One guarded PostgreSQL schema verifies durable investigation submissions."""

import asyncio
import importlib.util
import json
import os
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, delete, insert, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai.agents.core_agent import CoreAgentError, CoreAgentResult
from app.ai.agents.investigation_report import evidence_contract, render_report, validate_report
from app.ai.llm.base import LLMToolCall, LLMToolResponse
from app.api.v1.router import api_router
from app.core.exceptions import NotFoundError, register_exception_handlers
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.middleware.request_context import RequestContextMiddleware
from app.models.exception_case import ExceptionCase
from app.models.investigation_run import InvestigationRun
from app.models.order import Order
from app.services import investigation_run_service as runs

MIGRATION_DIR = Path(__file__).resolve().parents[2] / "alembic/versions"


class InvestigationRunsPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = make_url(os.environ["DAY6_TEST_DATABASE_URL"])
        if url.drivername != "postgresql+asyncpg" or url.database != "ragforge_day6_test":
            raise RuntimeError("Tests require ragforge_day6_test")
        self.schema = "investigation_run_test_" + uuid4().hex
        self.base = create_async_engine(url, poolclass=NullPool)
        self.engine = create_async_engine(url, poolclass=NullPool,
            connect_args={"server_settings": {"search_path": self.schema}})
        self.created = False
        try:
            async with self.base.begin() as conn:
                if await conn.scalar(text("SELECT current_database()")) != "ragforge_day6_test":
                    raise RuntimeError("Wrong database")
                await conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
                self.created = True
            async with self.engine.begin() as conn:
                if await conn.scalar(text("SELECT current_schema()")) != self.schema:
                    raise RuntimeError("Wrong schema")
                metadata = MetaData()
                for name in ("organizations", "users", "organization_members", "workspaces",
                             "workspace_members", "orders", "exception_cases", "audit_logs"):
                    Base.metadata.tables[name].to_metadata(metadata)
                await conn.run_sync(metadata.create_all)
                modules = []
                for filename in ("0005_action_requests.py", "0006_action_request_review.py",
                                 "0007_customer_notifications.py", "0009_investigation_runs.py"):
                    spec = importlib.util.spec_from_file_location(filename, MIGRATION_DIR / filename)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    modules.append(module)
                def migrate(sync):
                    with Operations.context(MigrationContext.configure(sync)):
                        for module in modules:
                            module.upgrade()
                await conn.run_sync(migrate)
            self.org, self.other_org, self.user, self.other_user, self.admin, self.workspace = (
                uuid4() for _ in range(6))
            self.case = uuid4()
            self.order = uuid4()
            async with self.engine.begin() as conn:
                await conn.execute(insert(Base.metadata.tables["organizations"]).values(
                    id=self.org, name="Investigation test", slug=uuid4().hex))
                await conn.execute(insert(Base.metadata.tables["organizations"]).values(
                    id=self.other_org, name="Second investigation test", slug=uuid4().hex))
                for user in (self.user, self.other_user, self.admin):
                    await conn.execute(insert(Base.metadata.tables["users"]).values(
                        id=user, email=f"investigation-{user.hex}@example.com",
                        hashed_password="offline", full_name="Test user"))
                    await conn.execute(insert(Base.metadata.tables["organization_members"]).values(
                        id=uuid4(), organization_id=self.org, user_id=user,
                        role="admin" if user == self.admin else "member"))
                await conn.execute(insert(Base.metadata.tables["organization_members"]).values(
                    id=uuid4(), organization_id=self.other_org, user_id=self.user, role="member"))
                await conn.execute(insert(Base.metadata.tables["workspaces"]).values(
                    id=self.workspace, organization_id=self.org, name="SOP", slug=uuid4().hex,
                    description="", settings={}))
                await conn.execute(insert(Base.metadata.tables["workspace_members"]).values(
                    id=uuid4(), workspace_id=self.workspace, user_id=self.user, role="viewer"))
                await conn.execute(insert(Order).values(
                    id=self.order, organization_id=self.org, platform="test", store_key="test",
                    order_number=uuid4().hex, currency="USD", subtotal_amount=10,
                    total_amount=10, ordered_at=datetime.now(UTC)))
                await conn.execute(insert(ExceptionCase).values(
                    id=self.case, organization_id=self.org, order_id=self.order,
                    exception_type="other", problem_description="Controlled investigation case",
                    opened_at=datetime.now(UTC)))
            app = FastAPI()
            register_exception_handlers(app)
            app.add_middleware(RequestContextMiddleware)
            app.include_router(api_router, prefix="/api/v1")
            async def isolated_db():
                async with AsyncSession(self.engine, expire_on_commit=False) as db:
                    yield db
            app.dependency_overrides[get_db] = isolated_db
            # Unexpected server errors must preserve their traceback in this isolated test.
            self.client = AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=True),
                                      base_url="http://isolated")
            self.path = f"/api/v1/organizations/{self.org}/investigations"
            self.headers = {"Authorization": "Bearer " + create_access_token(subject=str(self.user))}
            self.other_headers = {"Authorization": "Bearer " + create_access_token(subject=str(self.other_user))}
            self.admin_headers = {"Authorization": "Bearer " + create_access_token(subject=str(self.admin))}
        except Exception:
            await self.asyncTearDown()
            raise

    async def asyncTearDown(self):
        if hasattr(self, "client"):
            await self.client.aclose()
        if self.created:
            async with self.base.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
            async with self.base.connect() as conn:
                self.assertFalse(await conn.scalar(text(
                    "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:name)"),
                    {"name": self.schema}))
        await self.engine.dispose()
        await self.base.dispose()

    def valid_result(self):
        trace = [{"tool": "get_exception_case", "result": {"status": "not_found"}}]
        report = validate_report(json.dumps(evidence_contract(trace)), trace)
        return CoreAgentResult(render_report(report, trace), trace, 1,
                               report.model_dump(mode="json"), "", [])

    def body(self):
        return {"case_id": str(self.case), "workspace_id": str(self.workspace),
                "require_knowledge": True}

    async def test_concurrent_key_and_saved_authorized_read(self):
        started, release = asyncio.Event(), asyncio.Event()
        calls = 0
        async def agent(*args, **kwargs):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return self.valid_result()
        headers = {**self.headers, "Idempotency-Key": "same-key"}
        with (patch("app.api.v1.endpoints.investigations.get_llm_provider", return_value=object()),
              patch("app.api.v1.endpoints.investigations.run_core_agent", side_effect=agent)):
            first = asyncio.create_task(self.client.post(self.path, json=self.body(), headers=headers))
            await started.wait()
            duplicate = await self.client.post(self.path, json=self.body(), headers=headers)
            self.assertEqual(duplicate.status_code, 202)
            run_id = duplicate.json()["id"]
            self.assertEqual((await self.client.get(
                self.path + "/submissions/same-key", headers=self.headers)).json()["status"], "running")
            conflict = await self.client.post(self.path, json={"case_id": str(uuid4())}, headers=headers)
            self.assertEqual(conflict.status_code, 409)
            release.set()
            completed = await first
            self.assertEqual(completed.status_code, 200)
            self.assertEqual(calls, 1)
            self.assertEqual(completed.json()["run_id"], run_id)
            second = await self.client.post(self.path, json=self.body(), headers=headers)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(calls, 1)
            self.assertEqual(second.json(), completed.json())
        async with self.engine.connect() as conn:
            rows = (await conn.execute(select(InvestigationRun.status))).scalars().all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0], "succeeded")
            self.assertTrue(await conn.scalar(text(
                "SELECT response IS NOT NULL AND jsonb_typeof(response) = 'object' "
                "FROM investigation_runs WHERE id=:id"), {"id": UUID(run_id)}))
        saved = await self.client.get(self.path + "/runs/" + run_id, headers=self.headers)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["result"], completed.json())
        self.assertEqual((await self.client.get(self.path + "/runs/" + run_id,
                                                headers=self.other_headers)).status_code, 404)
        async with self.engine.begin() as conn:
            await conn.execute(delete(Base.metadata.tables["workspace_members"]).where(
                Base.metadata.tables["workspace_members"].c.user_id == self.user))
        self.assertEqual((await self.client.get(self.path + "/runs/" + run_id,
                                                headers=self.headers)).status_code, 403)
        self.assertEqual((await self.client.get(self.path, headers=self.headers)).json(), [])
        async with self.engine.begin() as conn:
            await conn.execute(delete(Base.metadata.tables["organization_members"]).where(
                Base.metadata.tables["organization_members"].c.user_id == self.user,
                Base.metadata.tables["organization_members"].c.organization_id == self.org))
        self.assertEqual((await self.client.get(self.path + "/runs/" + run_id,
                                                headers=self.headers)).status_code, 403)

    async def test_controlled_provider_graph_report_is_saved(self):
        expected = self.valid_result()
        replies = [
            LLMToolResponse("", "controlled", "tool_use", [LLMToolCall(
                "one", "get_exception_case", {"case_id": str(self.case)})]),
            LLMToolResponse(json.dumps(expected.report), "controlled", "stop"),
        ]
        provider = type("ControlledProvider", (), {})()
        provider.generate_with_tools = AsyncMock(side_effect=replies)
        with (patch("app.api.v1.endpoints.investigations.get_llm_provider",
                    return_value=provider),
              patch("app.ai.tools.investigation_tools.exception_service.get_exception_case",
                    new_callable=AsyncMock, side_effect=NotFoundError("case absent"))):
            response = await self.client.post(self.path, json={"case_id": str(self.case)},
                headers={**self.headers, "Idempotency-Key": "controlled-graph"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["report"], expected.report)
        self.assertEqual(provider.generate_with_tools.await_count, 2)
        run_id = response.json()["run_id"]
        saved = await self.client.get(self.path + "/runs/" + run_id, headers=self.headers)
        self.assertEqual(saved.json()["result"], response.json())

    async def test_failure_deadline_and_unsaved_report(self):
        headers = {**self.headers, "Idempotency-Key": "failure-key"}
        async def fail(*args, **kwargs):
            raise CoreAgentError("private", error_code="model_failed")
        with (patch("app.api.v1.endpoints.investigations.get_llm_provider", return_value=object()),
              patch("app.api.v1.endpoints.investigations.run_core_agent", side_effect=fail)):
            response = await self.client.post(self.path, json={"case_id": str(self.case)}, headers=headers)
        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(response.json()["error"]["code"], "model_failed")
        status = (await self.client.get(self.path + "/submissions/failure-key",
                                        headers=self.headers)).json()
        self.assertEqual(status["status"], "failed", status)
        self.assertIsNotNone(status["finished_at"])
        self.assertIsNone(status["result"])
        async with self.engine.connect() as conn:
            self.assertTrue(await conn.scalar(text(
                "SELECT response IS NULL FROM investigation_runs WHERE id=:id"),
                {"id": UUID(status["id"])}))
        async with self.engine.begin() as conn:
            await conn.execute(update(InvestigationRun).where(InvestigationRun.id == UUID(status["id"])).values(
                status="running", error_code=None, finished_at=None,
                deadline_at=datetime.now(UTC) - timedelta(seconds=1)))
        expired = (await self.client.get(self.path + "/submissions/failure-key",
                                         headers=self.headers)).json()
        self.assertEqual(expired["status"], "interrupted")
        self.assertIsNone(expired["result"])
        async with self.engine.connect() as conn:
            self.assertTrue(await conn.scalar(text(
                "SELECT response IS NULL FROM investigation_runs WHERE id=:id"),
                {"id": UUID(status["id"])}))

    async def test_key_is_scoped_by_enterprise_and_user(self):
        calls = 0
        async def agent(*args, **kwargs):
            nonlocal calls
            calls += 1
            return self.valid_result()
        key = "same-text-key"
        with (patch("app.api.v1.endpoints.investigations.get_llm_provider", return_value=object()),
              patch("app.api.v1.endpoints.investigations.run_core_agent", side_effect=agent)):
            first = await self.client.post(self.path, json={"case_id": str(self.case)},
                                           headers={**self.headers, "Idempotency-Key": key})
            other_user = await self.client.post(self.path, json={"case_id": str(self.case)},
                headers={**self.other_headers, "Idempotency-Key": key})
            other_org = await self.client.post(
                f"/api/v1/organizations/{self.other_org}/investigations",
                json={"case_id": str(self.case)},
                headers={**self.headers, "Idempotency-Key": key})
        self.assertEqual([first.status_code, other_user.status_code, other_org.status_code],
                         [200, 200, 200])
        self.assertEqual(calls, 3)
        self.assertEqual(len({first.json()["run_id"], other_user.json()["run_id"],
                              other_org.json()["run_id"]}), 3)

    async def test_same_case_can_enter_existing_approval_and_internal_notification_flow(self):
        path = f"/api/v1/organizations/{self.org}/action-requests"
        created = await self.client.post(path, json={
            "target_case_id": str(self.case), "message": "Review this shipment update",
            "idempotency_key": "investigation-handoff",
        }, headers=self.headers)
        self.assertEqual(created.status_code, 200)
        request_id = created.json()["id"]
        reviewed = await self.client.post(path + f"/{request_id}/review",
            json={"decision": "approved"}, headers=self.admin_headers)
        self.assertEqual(reviewed.status_code, 200)
        executed = await self.client.post(path + f"/{request_id}/execute",
                                          headers=self.admin_headers)
        self.assertEqual(executed.status_code, 200)
        self.assertEqual(executed.json()["delivery_status"], "not_sent")
        async with self.engine.connect() as conn:
            audit_count = await conn.scalar(text(
                "SELECT count(*) FROM audit_logs WHERE organization_id=:org "
                "AND resource_id=:request_id"), {"org": self.org, "request_id": UUID(request_id)})
            self.assertEqual(audit_count, 3)

    async def test_bounded_model_and_result_save_failure(self):
        async def slow(*args, **kwargs):
            await asyncio.sleep(1)
            return self.valid_result()
        headers = {**self.headers, "Idempotency-Key": "timeout-key"}
        with (patch.object(runs, "OUTER_TIMEOUT_SECONDS", 0.05),
              patch("app.api.v1.endpoints.investigations.get_llm_provider", return_value=object()),
              patch("app.api.v1.endpoints.investigations.run_core_agent", side_effect=slow)):
            response = await self.client.post(self.path, json={"case_id": str(self.case)}, headers=headers)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "outer_timeout")
        state = (await self.client.get(self.path + "/submissions/timeout-key",
                                       headers=self.headers)).json()
        self.assertEqual(state["status"], "interrupted")
        self.assertIsNone(state["result"])

        save_headers = {**self.headers, "Idempotency-Key": "save-key"}
        async def ready(*args, **kwargs):
            return self.valid_result()
        with (patch("app.api.v1.endpoints.investigations.get_llm_provider", return_value=object()),
              patch("app.api.v1.endpoints.investigations.run_core_agent", side_effect=ready),
              patch("app.api.v1.endpoints.investigations.runs.finish",
                    side_effect=RuntimeError("save failure"))):
            failed = await self.client.post(self.path, json={"case_id": str(self.case)},
                                            headers=save_headers)
        self.assertEqual(failed.status_code, 502)
        self.assertNotIn("report", failed.json())
        state = (await self.client.get(self.path + "/submissions/save-key",
                                       headers=self.headers)).json()
        self.assertEqual(state["status"], "running")
        self.assertIsNone(state["result"])
        async with self.engine.begin() as conn:
            await conn.execute(update(InvestigationRun).where(InvestigationRun.id == UUID(state["id"])).values(
                executor_instance_id=uuid4()))
        restarted = (await self.client.get(self.path + "/submissions/save-key",
                                           headers=self.headers)).json()
        self.assertEqual(restarted["status"], "interrupted")
        self.assertEqual(restarted["error_code"], "service_restarted")
