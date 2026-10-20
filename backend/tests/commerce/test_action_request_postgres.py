"""ActionRequest contract against the migration in an isolated PostgreSQL schema."""

import asyncio
import importlib.util
import os
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, func, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.v1.router import api_router
from app.core.exceptions import (
    AlreadyExistsError,
    NotFoundError,
    PermissionDeniedError,
    ValidationAppError,
    register_exception_handlers,
)
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.models.action_request import ActionRequest
from app.models.audit import AuditLog
from app.models.customer_notification import CustomerNotification
from app.models.exception_case import ExceptionCase
from app.models.order import Order
from app.services.action_request_service import (
    create_notification_request,
    execute_approved_notification,
    get_internal_notification,
    review_action_request,
)

MIGRATION_DIR = Path(__file__).resolve().parents[2] / "alembic/versions"


class ActionRequestPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = make_url(os.environ["DAY6_TEST_DATABASE_URL"])
        if url.drivername != "postgresql+asyncpg" or url.database != "ragforge_day6_test":
            raise RuntimeError("ActionRequest tests require ragforge_day6_test")
        self.schema = "action_request_test_" + uuid4().hex
        self.base_engine = create_async_engine(url, poolclass=NullPool)
        self.engine = create_async_engine(
            url, poolclass=NullPool,
            connect_args={"server_settings": {"search_path": self.schema}},
        )
        self.schema_created = False
        try:
            async with self.base_engine.begin() as conn:
                self.assertEqual(await conn.scalar(text("SELECT current_database()")), "ragforge_day6_test")
                await conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
            self.schema_created = True
            async with self.engine.begin() as conn:
                self.assertEqual(await conn.scalar(text("SELECT current_schema()")), self.schema)
                metadata = MetaData()
                for name in ("organizations", "users", "organization_members", "orders",
                             "exception_cases", "audit_logs"):
                    Base.metadata.tables[name].to_metadata(metadata)
                await conn.run_sync(metadata.create_all)
                modules = []
                for filename in ("0005_action_requests.py", "0006_action_request_review.py",
                                 "0007_customer_notifications.py"):
                    spec = importlib.util.spec_from_file_location(filename, MIGRATION_DIR / filename)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    modules.append(module)
                def migrate(sync):
                    with Operations.context(MigrationContext.configure(sync)):
                        for module in modules:
                            module.upgrade()
                await conn.run_sync(migrate)
            self.orgs = [uuid4(), uuid4()]
            self.users = [uuid4(), uuid4()]
            self.reviewers = [uuid4(), uuid4()]
            self.orders = [uuid4(), uuid4()]
            self.cases = [uuid4(), uuid4()]
            async with self.engine.begin() as conn:
                for index in range(2):
                    await conn.execute(insert(Base.metadata.tables["organizations"]).values(
                        id=self.orgs[index], name="Action test", slug=uuid4().hex))
                    await conn.execute(insert(Base.metadata.tables["users"]).values(
                        id=self.users[index], email=f"action-{uuid4()}@example.invalid",
                        hashed_password="test", full_name="Action test"))
                    await conn.execute(insert(Base.metadata.tables["organization_members"]).values(
                        id=uuid4(), organization_id=self.orgs[index], user_id=self.users[index], role="member"))
                    await conn.execute(insert(Base.metadata.tables["users"]).values(
                        id=self.reviewers[index], email=f"reviewer-{uuid4()}@example.invalid",
                        hashed_password="test", full_name="Action reviewer"))
                    await conn.execute(insert(Base.metadata.tables["organization_members"]).values(
                        id=uuid4(), organization_id=self.orgs[index],
                        user_id=self.reviewers[index], role="admin"))
                    await conn.execute(insert(Order).values(
                        id=self.orders[index], organization_id=self.orgs[index], platform="test",
                        store_key="test", order_number=uuid4().hex, currency="USD",
                        subtotal_amount=10, total_amount=10, ordered_at=datetime.now(UTC)))
                    await conn.execute(insert(ExceptionCase).values(
                        id=self.cases[index], organization_id=self.orgs[index], order_id=self.orders[index],
                        exception_type="other", problem_description="Review before customer notification",
                        opened_at=datetime.now(UTC)))
        except BaseException:
            await self._cleanup()
            raise

    async def asyncTearDown(self):
        await self._cleanup()

    async def _cleanup(self):
        await self.engine.dispose()
        if self.schema_created:
            async with self.base_engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
            async with self.base_engine.connect() as conn:
                self.assertFalse(await conn.scalar(text(
                    "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:name)"),
                    {"name": self.schema}))
        await self.base_engine.dispose()

    def payload(self, index=0, **changes):
        values = dict(organization_id=self.orgs[index], requested_by_user_id=self.users[index],
                      target_case_id=self.cases[index], message="Please review this delivery update.",
                      idempotency_key="same-key")
        values.update(changes)
        return values

    async def counts(self):
        async with AsyncSession(self.engine) as db:
            requests = await db.scalar(select(func.count()).select_from(ActionRequest))
            audits = await db.scalar(select(func.count()).select_from(AuditLog))
            return requests, audits

    async def submit(self, **payload):
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            request = await create_notification_request(db, **payload)
            await db.commit()
            return request

    async def review(self, request_id, decision="approved", reviewer=None, organization=None):
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            request = await review_action_request(
                db, organization_id=organization or self.orgs[0], request_id=request_id,
                reviewer_user_id=reviewer or self.reviewers[0], decision=decision,
            )
            await db.commit()
            return request

    async def review_audits(self):
        async with AsyncSession(self.engine) as db:
            return (await db.execute(select(AuditLog).where(
                AuditLog.action == "action_request.reviewed"))).scalars().all()

    async def test_same_key_is_scoped_to_organization(self):
        first = await self.submit(**self.payload(0))
        second = await self.submit(**self.payload(1))
        self.assertNotEqual(first.id, second.id)
        self.assertEqual((first.status, second.status), ("pending_approval", "pending_approval"))
        self.assertEqual(await self.counts(), (2, 2))

    async def test_same_content_returns_original_without_second_audit(self):
        first = await self.submit(**self.payload())
        second = await self.submit(**self.payload())
        self.assertEqual(first.id, second.id)
        self.assertEqual(await self.counts(), (1, 1))

    async def test_same_key_changed_content_conflicts(self):
        await self.submit(**self.payload())
        with self.assertRaises(AlreadyExistsError):
            await self.submit(**self.payload(message="A different message."))
        self.assertEqual(await self.counts(), (1, 1))

    async def test_nonmember_and_foreign_case_are_rejected_before_write(self):
        with self.assertRaises(PermissionDeniedError):
            await self.submit(**self.payload(requested_by_user_id=self.users[1]))
        with self.assertRaises(NotFoundError):
            await self.submit(**self.payload(target_case_id=self.cases[1]))
        self.assertEqual(await self.counts(), (0, 0))

    async def test_pending_request_does_not_mutate_business_records(self):
        async with AsyncSession(self.engine) as db:
            before = (await db.scalar(select(Order.status).where(Order.id == self.orders[0])),
                      await db.scalar(select(ExceptionCase.status).where(ExceptionCase.id == self.cases[0])))
        request = await self.submit(**self.payload())
        async with AsyncSession(self.engine) as db:
            after = (await db.scalar(select(Order.status).where(Order.id == self.orders[0])),
                     await db.scalar(select(ExceptionCase.status).where(ExceptionCase.id == self.cases[0])))
            audit = (await db.execute(select(AuditLog))).scalar_one()
        self.assertEqual(before, after)
        self.assertEqual(request.status, "pending_approval")
        self.assertEqual(audit.resource_id, request.id)
        self.assertEqual(audit.organization_id, self.orgs[0])
        self.assertEqual(audit.user_id, self.users[0])
        self.assertEqual(await self.counts(), (1, 1))

    async def test_concurrent_same_key_creates_one_request_and_audit(self):
        async with AsyncSession(self.engine, expire_on_commit=False) as first_db:
            first = await create_notification_request(first_db, **self.payload())
            started = asyncio.Event()
            async def second_submit():
                async with AsyncSession(self.engine, expire_on_commit=False) as second_db:
                    started.set()
                    second = await create_notification_request(second_db, **self.payload())
                    await second_db.commit()
                    return second
            task = asyncio.create_task(second_submit())
            await started.wait()
            await asyncio.sleep(0.1)
            self.assertFalse(task.done())
            await first_db.commit()
            second = await asyncio.wait_for(task, timeout=10)
        self.assertEqual(first.id, second.id)
        self.assertEqual(await self.counts(), (1, 1))

    async def test_audit_failure_rolls_back_request_savepoint(self):
        async with AsyncSession(self.engine) as db:
            with (
                patch("app.services.action_request_service.record_audit_event",
                      side_effect=RuntimeError("audit unavailable")),
                self.assertRaises(RuntimeError),
            ):
                await create_notification_request(db, **self.payload())
            await db.commit()
        self.assertEqual(await self.counts(), (0, 0))

    async def test_approve_records_one_human_decision_without_execution(self):
        created = await self.submit(**self.payload())
        async with AsyncSession(self.engine) as db:
            before = (await db.scalar(select(Order.status).where(Order.id == self.orders[0])),
                      await db.scalar(select(ExceptionCase.status).where(ExceptionCase.id == self.cases[0])))
        approved = await self.review(created.id)
        async with AsyncSession(self.engine) as db:
            after = (await db.scalar(select(Order.status).where(Order.id == self.orders[0])),
                     await db.scalar(select(ExceptionCase.status).where(ExceptionCase.id == self.cases[0])))
        self.assertEqual(before, after)
        self.assertEqual(approved.status, "approved")
        self.assertEqual(approved.review_decision, "approved")
        self.assertEqual(approved.reviewed_by_user_id, self.reviewers[0])
        self.assertIsNotNone(approved.reviewed_at)
        self.assertEqual(len(await self.review_audits()), 1)
        self.assertEqual(await self.counts(), (1, 2))

    async def test_reject_records_decision_and_repeated_review_conflicts(self):
        created = await self.submit(**self.payload())
        rejected = await self.review(created.id, decision="rejected")
        self.assertEqual((rejected.status, rejected.review_decision), ("rejected", "rejected"))
        with self.assertRaises(AlreadyExistsError):
            await self.review(created.id, decision="approved")
        with self.assertRaises(AlreadyExistsError):
            await self.review(created.id, decision="rejected")
        audits = await self.review_audits()
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].audit_metadata, {"decision": "rejected"})

    async def test_review_requires_admin_in_same_organization(self):
        created = await self.submit(**self.payload())
        with self.assertRaises(PermissionDeniedError):
            await self.review(created.id, reviewer=self.users[0])
        with self.assertRaises(PermissionDeniedError):
            await self.review(created.id, reviewer=self.reviewers[1])
        with self.assertRaises(NotFoundError):
            await self.review(created.id, reviewer=self.reviewers[1], organization=self.orgs[1])
        self.assertEqual(len(await self.review_audits()), 0)
        async with AsyncSession(self.engine) as db:
            request = await db.get(ActionRequest, created.id)
            self.assertEqual(request.status, "pending_approval")

    async def test_concurrent_reviews_persist_one_decision_and_audit(self):
        created = await self.submit(**self.payload())
        async with AsyncSession(self.engine, expire_on_commit=False) as first_db:
            approved = await review_action_request(
                first_db, organization_id=self.orgs[0], request_id=created.id,
                reviewer_user_id=self.reviewers[0], decision="approved")
            started = asyncio.Event()
            async def competing_review():
                async with AsyncSession(self.engine) as second_db:
                    # Cache the pre-commit state so the locked read must refresh it.
                    cached = await second_db.get(ActionRequest, created.id)
                    self.assertEqual(cached.status, "pending_approval")
                    started.set()
                    return await review_action_request(
                        second_db, organization_id=self.orgs[0], request_id=created.id,
                        reviewer_user_id=self.reviewers[0], decision="rejected")
            task = asyncio.create_task(competing_review())
            await started.wait()
            await asyncio.sleep(0.1)
            self.assertFalse(task.done())
            await first_db.commit()
            with self.assertRaises(AlreadyExistsError):
                await asyncio.wait_for(task, timeout=10)
        self.assertEqual(approved.status, "approved")
        self.assertEqual(len(await self.review_audits()), 1)
        async with AsyncSession(self.engine) as db:
            request = await db.get(ActionRequest, created.id)
            self.assertEqual((request.status, request.review_decision), ("approved", "approved"))

    async def test_review_audit_failure_rolls_back_decision(self):
        created = await self.submit(**self.payload())
        async with AsyncSession(self.engine) as db:
            with (
                patch("app.services.action_request_service.record_audit_event",
                      side_effect=RuntimeError("audit unavailable")),
                self.assertRaises(RuntimeError),
            ):
                await review_action_request(
                    db, organization_id=self.orgs[0], request_id=created.id,
                    reviewer_user_id=self.reviewers[0], decision="approved")
            await db.commit()
        async with AsyncSession(self.engine) as db:
            request = await db.get(ActionRequest, created.id)
            self.assertEqual(request.status, "pending_approval")
            self.assertIsNone(request.review_decision)
            self.assertIsNone(request.reviewed_at)
        self.assertEqual(len(await self.review_audits()), 0)

    async def test_authenticated_review_api_enforces_role_and_single_decision(self):
        created = await self.submit(**self.payload())
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(api_router, prefix="/api/v1")
        async def isolated_db():
            async with AsyncSession(self.engine, expire_on_commit=False) as db:
                yield db
        app.dependency_overrides[get_db] = isolated_db
        url = f"/api/v1/organizations/{self.orgs[0]}/action-requests/{created.id}/review"
        def auth(user_id):
            token = create_access_token(subject=str(user_id), organization_id=str(self.orgs[0]))
            return {"Authorization": "Bearer " + token}
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://isolated") as client:
            unauthenticated = await client.post(url, json={"decision": "approved"})
            member = await client.post(url, json={"decision": "approved"}, headers=auth(self.users[0]))
            other_org = await client.post(url, json={"decision": "approved"},
                                          headers=auth(self.reviewers[1]))
            malformed = await client.post(url, json={"decision": "executed"},
                                          headers=auth(self.reviewers[0]))
            approved = await client.post(url, json={"decision": "approved"},
                                         headers=auth(self.reviewers[0]))
            repeated = await client.post(url, json={"decision": "rejected"},
                                         headers=auth(self.reviewers[0]))
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(member.status_code, 403)
        self.assertEqual(other_org.status_code, 403)
        self.assertEqual(malformed.status_code, 422)
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "approved")
        self.assertEqual(approved.json()["review_decision"], "approved")
        self.assertEqual(approved.json()["reviewed_by_user_id"], str(self.reviewers[0]))
        self.assertNotIn("parameters", approved.json())
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(len(await self.review_audits()), 1)

    async def test_authenticated_creation_and_review_http_chain_commits_to_independent_sessions(self):
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(api_router, prefix="/api/v1")

        async def isolated_db():
            async with AsyncSession(self.engine, expire_on_commit=False) as db:
                yield db

        app.dependency_overrides[get_db] = isolated_db
        create_url = f"/api/v1/organizations/{self.orgs[0]}/action-requests"
        other_url = f"/api/v1/organizations/{self.orgs[1]}/action-requests"

        def auth(user_id):
            token = create_access_token(subject=str(user_id), organization_id=str(self.orgs[0]))
            return {"Authorization": "Bearer " + token}

        body = {
            "target_case_id": str(self.cases[0]),
            "message": "Please review this delivery update.",
            "idempotency_key": "http-approve",
        }
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://isolated") as client:
            unauthenticated = await client.post(create_url, json=body)
            cross_org = await client.post(other_url, json=body, headers=auth(self.users[0]))
            foreign_case = await client.post(
                create_url, json={**body, "target_case_id": str(self.cases[1])},
                headers=auth(self.users[0]),
            )
            forged = await client.post(
                create_url,
                json={**body, "organization_id": str(self.orgs[1]),
                      "requested_by_user_id": str(self.reviewers[0]), "status": "approved"},
                headers=auth(self.users[0]),
            )
            created = await client.post(create_url, json=body, headers=auth(self.users[0]))
            duplicate = await client.post(create_url, json=body, headers=auth(self.users[0]))
            conflict = await client.post(
                create_url, json={**body, "message": "A different message"},
                headers=auth(self.users[0]),
            )

            self.assertEqual(unauthenticated.status_code, 401)
            self.assertEqual(cross_org.status_code, 403)
            self.assertEqual(foreign_case.status_code, 404)
            self.assertEqual(forged.status_code, 422)
            self.assertEqual(created.status_code, 200, created.text)
            self.assertEqual(duplicate.status_code, 200, duplicate.text)
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(created.json()["id"], duplicate.json()["id"])
            self.assertEqual(created.json()["organization_id"], str(self.orgs[0]))
            self.assertEqual(created.json()["requested_by_user_id"], str(self.users[0]))
            self.assertEqual(created.json()["target_case_id"], str(self.cases[0]))
            self.assertEqual(created.json()["action_type"], "notify_case_customer")
            self.assertEqual(created.json()["status"], "pending_approval")
            self.assertIn("created_at", created.json())
            self.assertNotIn("parameters", created.json())

            first_id = created.json()["id"]
            async with AsyncSession(self.engine) as independent_db:
                committed = await independent_db.get(ActionRequest, UUID(first_id))
                self.assertEqual(committed.status, "pending_approval")
                self.assertEqual(committed.requested_by_user_id, self.users[0])
                first_audits = (await independent_db.execute(select(AuditLog).where(
                    AuditLog.resource_id == UUID(first_id)))).scalars().all()
                self.assertEqual([audit.action for audit in first_audits], ["action_request.created"])

            review_url = create_url + f"/{first_id}/review"
            member_review = await client.post(
                review_url, json={"decision": "approved"}, headers=auth(self.users[0]),
            )
            approved = await client.post(
                review_url, json={"decision": "approved"}, headers=auth(self.reviewers[0]),
            )
            self.assertEqual(member_review.status_code, 403)
            self.assertEqual(approved.status_code, 200, approved.text)
            self.assertEqual(approved.json()["status"], "approved")

            reject_body = {**body, "idempotency_key": "http-reject"}
            second = await client.post(create_url, json=reject_body, headers=auth(self.users[0]))
            self.assertEqual(second.status_code, 200, second.text)
            second_id = second.json()["id"]
            self.assertNotEqual(first_id, second_id)
            rejected = await client.post(
                create_url + f"/{second_id}/review", json={"decision": "rejected"},
                headers=auth(self.reviewers[0]),
            )
            self.assertEqual(rejected.status_code, 200, rejected.text)
            self.assertEqual(rejected.json()["status"], "rejected")

        async with AsyncSession(self.engine) as independent_db:
            requests = (await independent_db.execute(select(ActionRequest).order_by(
                ActionRequest.created_at))).scalars().all()
            self.assertEqual({request.status for request in requests}, {"approved", "rejected"})
            self.assertEqual({str(request.id) for request in requests}, {first_id, second_id})
            audits = (await independent_db.execute(select(AuditLog).where(
                AuditLog.resource_id.in_([UUID(first_id), UUID(second_id)])))).scalars().all()
            self.assertEqual(len(audits), 4)
            self.assertEqual(sorted(audit.action for audit in audits),
                             ["action_request.created", "action_request.created",
                              "action_request.reviewed", "action_request.reviewed"])
            orders = (await independent_db.execute(select(Order).order_by(Order.id))).scalars().all()
            cases = (await independent_db.execute(select(ExceptionCase).order_by(ExceptionCase.id))).scalars().all()
            self.assertEqual(len(orders), 2)
            self.assertEqual(len(cases), 2)

    async def test_action_request_list_is_scoped_to_member_and_admin(self):
        own = await self.submit(**self.payload(idempotency_key="member-list"))
        admin_owned = await self.submit(**self.payload(
            requested_by_user_id=self.reviewers[0], idempotency_key="admin-list",
        ))
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(api_router, prefix="/api/v1")

        async def isolated_db():
            async with AsyncSession(self.engine, expire_on_commit=False) as db:
                yield db

        app.dependency_overrides[get_db] = isolated_db
        url = f"/api/v1/organizations/{self.orgs[0]}/action-requests"

        def auth(user_id):
            token = create_access_token(subject=str(user_id), organization_id=str(self.orgs[0]))
            return {"Authorization": "Bearer " + token}

        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://isolated") as client:
            unauthenticated = await client.get(url)
            other_org = await client.get(url, headers=auth(self.users[1]))
            member = await client.get(url, headers=auth(self.users[0]))
            admin = await client.get(url, headers=auth(self.reviewers[0]))
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(other_org.status_code, 403)
        self.assertEqual(member.status_code, 200)
        self.assertEqual(admin.status_code, 200)
        self.assertEqual([item["id"] for item in member.json()], [str(own.id)])
        self.assertEqual({item["id"] for item in admin.json()}, {str(own.id), str(admin_owned.id)})
        self.assertTrue(all("parameters" not in item for item in admin.json()))

    async def test_list_exposes_real_review_and_internal_execution_times(self):
        pending = await self.submit(**self.payload(idempotency_key="time-pending"))
        approved = await self.submit(**self.payload(idempotency_key="time-approved"))
        executed = await self.submit(**self.payload(idempotency_key="time-executed"))
        await self.review(approved.id)
        await self.review(executed.id)
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            notification = await execute_approved_notification(
                db, organization_id=self.orgs[0], request_id=executed.id,
                executor_user_id=self.reviewers[0],
            )
            await db.commit()
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(api_router, prefix="/api/v1")

        async def isolated_db():
            async with AsyncSession(self.engine, expire_on_commit=False) as db:
                yield db

        app.dependency_overrides[get_db] = isolated_db
        token = create_access_token(subject=str(self.reviewers[0]), organization_id=str(self.orgs[0]))
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://isolated") as client:
            response = await client.get(
                f"/api/v1/organizations/{self.orgs[0]}/action-requests",
                headers={"Authorization": "Bearer " + token},
            )
        self.assertEqual(response.status_code, 200, response.text)
        by_id = {item["id"]: item for item in response.json()}
        self.assertEqual(set(by_id), {str(pending.id), str(approved.id), str(executed.id)})
        self.assertIsNone(by_id[str(pending.id)]["review_decision"])
        self.assertIsNone(by_id[str(pending.id)]["reviewed_at"])
        self.assertIsNone(by_id[str(pending.id)]["executed_at"])
        self.assertEqual(by_id[str(approved.id)]["review_decision"], "approved")
        self.assertIsNotNone(by_id[str(approved.id)]["reviewed_at"])
        self.assertIsNone(by_id[str(approved.id)]["executed_at"])
        self.assertEqual(by_id[str(executed.id)]["review_decision"], "approved")
        self.assertIsNotNone(by_id[str(executed.id)]["reviewed_at"])
        self.assertEqual(datetime.fromisoformat(by_id[str(executed.id)]["executed_at"]),
                         notification.created_at)
        self.assertTrue(all("parameters" not in item for item in by_id.values()))

    async def test_approved_execution_creates_internal_record_and_audit(self):
        created = await self.submit(**self.payload())
        await self.review(created.id)
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            notification = await execute_approved_notification(
                db, organization_id=self.orgs[0], request_id=created.id,
                executor_user_id=self.reviewers[0],
            )
            await db.commit()
        async with AsyncSession(self.engine) as independent_db:
            request = await independent_db.get(ActionRequest, created.id)
            record = await independent_db.get(CustomerNotification, notification.id)
            audits = (await independent_db.execute(select(AuditLog).where(
                AuditLog.action == "action_request.executed"))).scalars().all()
            self.assertEqual(request.status, "executed")
            self.assertEqual(record.delivery_status, "not_sent")
            self.assertEqual(record.content, self.payload()["message"])
            self.assertEqual(record.action_request_id, created.id)
            self.assertEqual(record.created_by_user_id, self.reviewers[0])
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].audit_metadata["notification_id"], str(record.id))
            own = await get_internal_notification(
                independent_db, organization_id=self.orgs[0], request_id=created.id,
                viewer_user_id=self.users[0],
            )
            self.assertEqual(own.id, record.id)

    async def test_execution_rejects_pending_rejected_cross_org_and_member(self):
        pending = await self.submit(**self.payload(idempotency_key="pending"))
        rejected = await self.submit(**self.payload(idempotency_key="rejected"))
        await self.review(rejected.id, decision="rejected")
        async with AsyncSession(self.engine) as db:
            with self.assertRaises(ValidationAppError):
                await execute_approved_notification(
                    db, organization_id=self.orgs[0], request_id=pending.id,
                    executor_user_id=self.reviewers[0],
                )
            with self.assertRaises(ValidationAppError):
                await execute_approved_notification(
                    db, organization_id=self.orgs[0], request_id=rejected.id,
                    executor_user_id=self.reviewers[0],
                )
            with self.assertRaises(NotFoundError):
                await execute_approved_notification(
                    db, organization_id=self.orgs[1], request_id=pending.id,
                    executor_user_id=self.reviewers[1],
                )
            with self.assertRaises(PermissionDeniedError):
                await execute_approved_notification(
                    db, organization_id=self.orgs[0], request_id=pending.id,
                    executor_user_id=self.users[0],
                )
            self.assertEqual(await db.scalar(select(func.count()).select_from(CustomerNotification)), 0)
            self.assertEqual(await db.scalar(select(func.count()).select_from(AuditLog).where(
                AuditLog.action == "action_request.executed")), 0)

    async def test_repeated_and_concurrent_execution_create_one_record(self):
        created = await self.submit(**self.payload())
        await self.review(created.id)
        async with AsyncSession(self.engine, expire_on_commit=False) as first_db:
            first = await execute_approved_notification(
                first_db, organization_id=self.orgs[0], request_id=created.id,
                executor_user_id=self.reviewers[0],
            )
            started = asyncio.Event()

            async def competing_execution():
                async with AsyncSession(self.engine, expire_on_commit=False) as second_db:
                    cached = await second_db.get(ActionRequest, created.id)
                    self.assertEqual(cached.status, "approved")
                    started.set()
                    second = await execute_approved_notification(
                        second_db, organization_id=self.orgs[0], request_id=created.id,
                        executor_user_id=self.reviewers[0],
                    )
                    await second_db.commit()
                    return second

            task = asyncio.create_task(competing_execution())
            await started.wait()
            await asyncio.sleep(0.1)
            self.assertFalse(task.done())
            await first_db.commit()
            second = await asyncio.wait_for(task, timeout=10)
        self.assertEqual(first.id, second.id)
        async with AsyncSession(self.engine) as db:
            again = await execute_approved_notification(
                db, organization_id=self.orgs[0], request_id=created.id,
                executor_user_id=self.reviewers[0],
            )
            self.assertEqual(again.id, first.id)
            self.assertEqual(await db.scalar(select(func.count()).select_from(CustomerNotification)), 1)
            self.assertEqual(await db.scalar(select(func.count()).select_from(AuditLog).where(
                AuditLog.action == "action_request.executed")), 1)

    async def test_database_rejects_second_notification_for_same_request(self):
        created = await self.submit(**self.payload())
        await self.review(created.id)
        async with AsyncSession(self.engine) as db:
            await execute_approved_notification(
                db, organization_id=self.orgs[0], request_id=created.id,
                executor_user_id=self.reviewers[0],
            )
            await db.commit()
        with self.assertRaises(IntegrityError):
            async with self.engine.begin() as conn:
                await conn.execute(insert(CustomerNotification).values(
                    id=uuid4(), organization_id=self.orgs[0], action_request_id=created.id,
                    target_case_id=self.cases[0], created_by_user_id=self.reviewers[0],
                    content="duplicate", delivery_status="not_sent",
                ))
        async with AsyncSession(self.engine) as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(CustomerNotification)), 1)

    async def test_execution_audit_failure_rolls_back_record_and_status(self):
        created = await self.submit(**self.payload())
        await self.review(created.id)
        async with AsyncSession(self.engine) as db:
            with (
                patch("app.services.action_request_service.record_audit_event",
                      side_effect=RuntimeError("audit unavailable")),
                self.assertRaises(RuntimeError),
            ):
                await execute_approved_notification(
                    db, organization_id=self.orgs[0], request_id=created.id,
                    executor_user_id=self.reviewers[0],
                )
            await db.commit()
        async with AsyncSession(self.engine) as independent_db:
            request = await independent_db.get(ActionRequest, created.id)
            self.assertEqual(request.status, "approved")
            self.assertEqual(await independent_db.scalar(
                select(func.count()).select_from(CustomerNotification)), 0)

    async def test_authenticated_execution_http_and_record_visibility(self):
        approved_request = await self.submit(**self.payload())
        pending_request = await self.submit(**self.payload(idempotency_key="pending-http"))
        await self.review(approved_request.id)
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(api_router, prefix="/api/v1")

        async def isolated_db():
            async with AsyncSession(self.engine, expire_on_commit=False) as db:
                yield db

        app.dependency_overrides[get_db] = isolated_db
        root = f"/api/v1/organizations/{self.orgs[0]}/action-requests"

        def auth(user_id):
            token = create_access_token(subject=str(user_id), organization_id=str(self.orgs[0]))
            return {"Authorization": "Bearer " + token}

        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://isolated") as client:
            execute_url = root + f"/{approved_request.id}/execute"
            unauthenticated = await client.post(execute_url)
            member = await client.post(execute_url, headers=auth(self.users[0]))
            pending = await client.post(root + f"/{pending_request.id}/execute",
                                        headers=auth(self.reviewers[0]))
            cross_org = await client.post(
                f"/api/v1/organizations/{self.orgs[1]}/action-requests/{approved_request.id}/execute",
                headers=auth(self.reviewers[1]),
            )
            executed = await client.post(execute_url, headers=auth(self.reviewers[0]))
            duplicate = await client.post(execute_url, headers=auth(self.reviewers[0]))
            visible = await client.get(root + f"/{approved_request.id}/notification",
                                       headers=auth(self.users[0]))
            foreign = await client.get(
                f"/api/v1/organizations/{self.orgs[1]}/action-requests/{approved_request.id}/notification",
                headers=auth(self.users[1]),
            )
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(member.status_code, 403)
        self.assertEqual(pending.status_code, 422)
        self.assertEqual(cross_org.status_code, 404)
        self.assertEqual(executed.status_code, 200, executed.text)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.json()["id"], executed.json()["id"])
        self.assertEqual(executed.json()["delivery_status"], "not_sent")
        self.assertEqual(visible.status_code, 200)
        self.assertEqual(visible.json()["content"], self.payload()["message"])
        self.assertEqual(foreign.status_code, 404)
        async with AsyncSession(self.engine) as db:
            self.assertEqual((await db.get(ActionRequest, approved_request.id)).status, "executed")
            self.assertEqual(await db.scalar(select(func.count()).select_from(CustomerNotification)), 1)
            self.assertEqual(await db.scalar(select(func.count()).select_from(AuditLog).where(
                AuditLog.action == "action_request.executed")), 1)
