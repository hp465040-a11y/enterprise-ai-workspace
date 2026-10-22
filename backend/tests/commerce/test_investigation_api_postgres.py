"""HTTP authorization with real JWT, users and membership in guarded test PG."""

import json
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession
from test_day6_postgres import Day6PostgresTests

from app.ai.agents.core_agent import CoreAgentResult
from app.ai.agents.investigation_report import evidence_contract, render_report, validate_report
from app.api.v1.router import api_router
from app.core.exceptions import NotFoundError, register_exception_handlers
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.middleware.request_context import RequestContextMiddleware
from app.models.exception_case import ExceptionCase
from app.models.order import Order
from app.services.exception_service import get_exception_case


class InvestigationAPIPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_login_membership_scope_and_database_failure(self):
        # Day6's context checks URL and current_database before creating a random
        # schema; its outer transaction removes all data and DDL on every exit.
        helper = Day6PostgresTests()
        async with helper.database("models") as (conn, own_org, own_order):
            for name in ("users", "organization_members", "refresh_tokens",
                         "workspaces", "workspace_members", "investigation_runs"):
                await conn.run_sync(Base.metadata.tables[name].create)

            other_org, other_order, user_id = uuid4(), uuid4(), uuid4()
            own_case, other_case = uuid4(), uuid4()
            email = f"api-{uuid4().hex}@example.invalid"
            password = "offline-test-password"
            await conn.execute(insert(Base.metadata.tables["organizations"]).values(
                id=other_org, name="Other test organization", slug=uuid4().hex,
            ))
            await conn.execute(insert(Order).values(
                id=other_order, organization_id=other_org, platform="test-platform",
                store_key="test-store", order_number="API-" + uuid4().hex,
                currency="USD", subtotal_amount=10, total_amount=10,
                ordered_at=datetime.now(UTC),
            ))
            await conn.execute(insert(Base.metadata.tables["users"]).values(
                id=user_id, email=email, hashed_password=hash_password(password),
                full_name="API test user", is_active=True,
            ))
            await conn.execute(insert(Base.metadata.tables["organization_members"]).values(
                id=uuid4(), organization_id=own_org, user_id=user_id, role="member",
            ))
            for case_id, org_id, order_id in (
                (own_case, own_org, own_order), (other_case, other_org, other_order),
            ):
                case = helper.case(org_id, order_id)
                case["id"] = case_id
                await conn.execute(insert(ExceptionCase).values(**case))

            async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint",
                                    expire_on_commit=False) as db:
                async def isolated_db():
                    yield db

                app = FastAPI()
                register_exception_handlers(app)
                app.add_middleware(RequestContextMiddleware)
                app.include_router(api_router, prefix="/api/v1")
                app.dependency_overrides[get_db] = isolated_db
                provider = object()
                calls = []

                async def agent_stub(_provider, agent_db, *, organization_id, case_id, as_of):
                    calls.append((organization_id, case_id, as_of))
                    self.assertIs(_provider, provider)
                    self.assertIsInstance(agent_db, AsyncSession)
                    self.assertIsNot(agent_db, db)
                    try:
                        await get_exception_case(agent_db, organization_id=organization_id,
                                                 case_id=case_id)
                    except NotFoundError:
                        trace = [{"tool": "get_exception_case", "result": {"status": "not_found"}}]
                    else:
                        trace = [{"tool": "analyze_fulfillment", "result": {
                            "status": "found", "analysis": {"shipment": {"status": "unknown"},
                                                       "delivery": {"status": "unknown"},
                                                       "evidence_event_ids": []}}}]
                    report = validate_report(json.dumps(evidence_contract(trace)), trace)
                    return CoreAgentResult(render_report(report, trace), trace, 0,
                                           report.model_dump(mode="json"), "", [])

                with (patch("app.api.v1.endpoints.investigations.get_llm_provider",
                            return_value=provider),
                      patch("app.api.v1.endpoints.investigations.run_core_agent",
                            new_callable=AsyncMock, side_effect=agent_stub) as agent):
                    async with AsyncClient(transport=ASGITransport(app=app,
                                                                  raise_app_exceptions=False),
                                           base_url="http://isolated") as client:
                        def path(org):
                            return f"/api/v1/organizations/{org}/investigations"

                        body = {"case_id": str(own_case)}
                        response = await client.post(path(own_org), json=body)
                        self.assertEqual(response.status_code, 401)
                        agent.assert_not_awaited()

                        login = await client.post("/api/v1/auth/login",
                                                  data={"username": email, "password": password})
                        self.assertEqual(login.status_code, 200)
                        headers = {"Authorization": "Bearer " + login.json()["access_token"]}

                        for case_id in (own_case, other_case):
                            response = await client.post(path(other_org),
                                                         json={"case_id": str(case_id)},
                                                         headers=headers)
                            self.assertEqual(response.status_code, 403)
                            self.assertEqual(response.json()["error"]["code"],
                                             "permission_denied")
                        agent.assert_not_awaited()

                        response = await client.post(path(own_org), json=body, headers=headers)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json()["report"]["outcome"],
                                         "insufficient_evidence")
                        self.assertEqual(calls[-1][:2], (own_org, own_case))

                        # The other tenant's real case exists, but the verified
                        # organization passed to the stub cannot retrieve it.
                        response = await client.post(path(own_org),
                                                     json={"case_id": str(other_case)},
                                                     headers=headers)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json()["report"]["outcome"], "not_found")
                        self.assertEqual(calls[-1][:2], (own_org, other_case))

                        before_fault = agent.await_count
                        real_execute = db.execute

                        async def fail_membership_read(statement, *args, **kwargs):
                            if (getattr(statement, "_raw_columns", None)
                                    and statement._raw_columns[0].name == "organization_members"):
                                # PostgreSQL itself raises the error at the
                                # membership-query execution boundary.
                                return await real_execute(text("SELECT 1 / 0"))
                            return await real_execute(statement, *args, **kwargs)

                        with patch.object(db, "execute", side_effect=fail_membership_read):
                            response = await client.post(path(own_org), json=body,
                                                         headers=headers)
                        self.assertEqual(response.status_code, 500)
                        self.assertEqual(response.json()["error"]["code"], "internal_error")
                        self.assertNotIn("report", response.json())
                        self.assertEqual(agent.await_count, before_fault)

        # Day6's context asserts the random schema no longer exists here.
