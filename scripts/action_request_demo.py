"""Disposable, persistent ActionRequest browser demo in ragforge_day6_test only."""

import argparse
import asyncio
import importlib.util
import json
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from dotenv import dotenv_values
from fastapi import FastAPI
from sqlalchemy import MetaData, insert, select, text, update
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
STATE = ROOT / "scripts" / "action_request_demo_state.json"
values = {**dotenv_values(ROOT / ".env"), **os.environ}
db_password = values.get("POSTGRES_PASSWORD")
if not db_password:
    raise RuntimeError("POSTGRES_PASSWORD is required for the isolated test database")
URL_TEST = URL.create(
    "postgresql+asyncpg",
    username=values.get("POSTGRES_USER") or "ragforge",
    password=db_password,
    host="localhost", port=5433, database="ragforge_day6_test",
)
os.environ["DATABASE_URL"] = URL_TEST.render_as_string(hide_password=False)

from app.api.v1.router import api_router
from app.core.exceptions import register_exception_handlers
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.models.action_request import ActionRequest
from app.models.audit import AuditLog
from app.models.customer_notification import CustomerNotification
from app.models.exception_case import ExceptionCase
from app.models.order import Order
from app.models.user import User


def load_state():
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if not state["schema"].startswith("action_demo_"):
        raise RuntimeError("Unexpected demo schema")
    return state


def engines(schema):
    base = create_async_engine(URL_TEST, poolclass=NullPool)
    scoped = create_async_engine(
        URL_TEST, poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    return base, scoped


async def assert_database(conn):
    if await conn.scalar(text("SELECT current_database()")) != "ragforge_day6_test":
        raise RuntimeError("Refusing a non-test database")


async def prepare():
    if STATE.exists():
        raise RuntimeError(f"Demo state already exists: {STATE}; inspect or clean it first")
    schema = "action_demo_" + uuid4().hex
    base, scoped = engines(schema)
    created = False
    try:
        async with base.begin() as conn:
            await assert_database(conn)
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        async with scoped.begin() as conn:
            if await conn.scalar(text("SELECT current_schema()")) != schema:
                raise RuntimeError("Search path did not select demo schema")
            metadata = MetaData()
            for name in ("organizations", "users", "organization_members", "refresh_tokens",
                         "orders", "exception_cases", "audit_logs"):
                Base.metadata.tables[name].to_metadata(metadata)
            await conn.run_sync(metadata.create_all)
            modules = []
            for filename in ("0005_action_requests.py", "0006_action_request_review.py",
                             "0007_customer_notifications.py"):
                spec = importlib.util.spec_from_file_location(filename, ROOT / "backend/alembic/versions" / filename)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                modules.append(module)

            def migrate(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    for module in modules:
                        module.upgrade()

            await conn.run_sync(migrate)
        org_id, other_org_id = uuid4(), uuid4()
        member_id, admin_id, outsider_id = uuid4(), uuid4(), uuid4()
        case_id, other_case_id = uuid4(), uuid4()
        password = secrets.token_urlsafe(18)
        async with scoped.begin() as conn:
            for oid, suffix in ((org_id, "main"), (other_org_id, "other")):
                await conn.execute(insert(Base.metadata.tables["organizations"]).values(
                    id=oid, name=f"Project A demo {suffix}", slug=uuid4().hex))
            for uid, role, oid in ((member_id, "member", org_id),
                                   (admin_id, "admin", org_id),
                                   (outsider_id, "member", other_org_id)):
                await conn.execute(insert(Base.metadata.tables["users"]).values(
                    id=uid, email=f"action-demo-{role}-{uid.hex[:8]}@example.com",
                    hashed_password=hash_password(password), full_name=f"Demo {role}"))
                await conn.execute(insert(Base.metadata.tables["organization_members"]).values(
                    id=uuid4(), organization_id=oid, user_id=uid, role=role))
            for oid, cid in ((org_id, case_id), (other_org_id, other_case_id)):
                order_id = uuid4()
                await conn.execute(insert(Order).values(
                    id=order_id, organization_id=oid, platform="demo", store_key="demo",
                    order_number=uuid4().hex, currency="USD", subtotal_amount=10,
                    total_amount=10, ordered_at=datetime.now(UTC)))
                await conn.execute(insert(ExceptionCase).values(
                    id=cid, organization_id=oid, order_id=order_id,
                    exception_type="other", problem_description="Demo notification review",
                    opened_at=datetime.now(UTC)))
        state = {
            "database": "ragforge_day6_test", "schema": schema, "organization_id": str(org_id),
            "other_organization_id": str(other_org_id), "case_id": str(case_id),
            "other_case_id": str(other_case_id), "member_id": str(member_id),
            "admin_id": str(admin_id), "outsider_id": str(outsider_id),
            "password": password,
            "emails": {
                "member": f"action-demo-member-{member_id.hex[:8]}@example.com",
                "admin": f"action-demo-admin-{admin_id.hex[:8]}@example.com",
                "outsider": f"action-demo-member-{outsider_id.hex[:8]}@example.com",
            },
        }
        STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in state.items() if key not in ("password", "emails")}))
    except BaseException:
        if created:
            async with base.begin() as conn:
                await assert_database(conn)
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        raise
    finally:
        await scoped.dispose()
        await base.dispose()


async def inspect():
    state = load_state()
    base, scoped = engines(state["schema"])
    try:
        async with base.connect() as conn:
            await assert_database(conn)
            exists = await conn.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:name)"),
                                       {"name": state["schema"]})
        if not exists:
            raise RuntimeError("Demo schema is missing")
        async with AsyncSession(scoped) as db:
            requests = (await db.execute(select(ActionRequest).order_by(ActionRequest.created_at))).scalars().all()
            audits = (await db.execute(select(AuditLog).where(
                AuditLog.resource_type == "action_request"))).scalars().all()
            notification_table = await db.scalar(text("SELECT to_regclass('customer_notifications') IS NOT NULL"))
            notifications = (await db.execute(select(CustomerNotification))).scalars().all() if notification_table else []
            print(json.dumps({
                "database": "ragforge_day6_test", "schema": state["schema"],
                "requests": [{"id": str(item.id), "status": item.status,
                              "organization_id": str(item.organization_id)} for item in requests],
                "audit_actions": [item.action for item in audits],
                "notification_table_exists": notification_table,
                "notifications": [{"id": str(item.id), "action_request_id": str(item.action_request_id),
                                   "delivery_status": item.delivery_status} for item in notifications],
                "schema_exists": exists,
            }))
    finally:
        await scoped.dispose()
        await base.dispose()


async def upgrade():
    """Add only the internal record table to the retained disposable schema."""
    state = load_state()
    base, scoped = engines(state["schema"])
    try:
        async with base.connect() as conn:
            await assert_database(conn)
            exists = await conn.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:name)"),
                                       {"name": state["schema"]})
            if not exists:
                raise RuntimeError("Demo schema is missing")
        async with scoped.begin() as conn:
            if await conn.scalar(text("SELECT current_schema()")) != state["schema"]:
                raise RuntimeError("Search path did not select demo schema")
            if await conn.scalar(text("SELECT to_regclass('customer_notifications') IS NOT NULL")):
                print("Demo notification table already exists")
                return
            filename = "0007_customer_notifications.py"
            spec = importlib.util.spec_from_file_location(filename, ROOT / "backend/alembic/versions" / filename)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            def migrate(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    module.upgrade()

            await conn.run_sync(migrate)
            print("Demo notification table created in retained test schema")
    finally:
        await scoped.dispose()
        await base.dispose()


async def repair_emails():
    """Correct only the retained demo users' invalid email domain in place."""
    state = load_state()
    if state["database"] != "ragforge_day6_test":
        raise RuntimeError("Refusing a non-test database")
    current = state["emails"]
    corrected = {role: (email if email.endswith("@example.com") else
                        email.removesuffix("@example.invalid") + "@example.com")
                 for role, email in current.items()}
    if set(current) != {"member", "admin", "outsider"} or not all(
        email.endswith(("@example.invalid", "@example.com")) for email in current.values()
    ):
        raise RuntimeError("Unexpected demo email mapping")
    _, scoped = engines(state["schema"])
    try:
        async with scoped.begin() as conn:
            await assert_database(conn)
            if await conn.scalar(text("SELECT current_schema()")) != state["schema"]:
                raise RuntimeError("Search path did not select demo schema")
            for role, user_key in (("member", "member_id"), ("admin", "admin_id"),
                                   ("outsider", "outsider_id")):
                user_id = UUID(state[user_key])
                email = (await conn.execute(select(User.email).where(User.id == user_id))).scalar_one()
                if email not in (current[role], corrected[role]):
                    raise RuntimeError("Demo user email differs from retained state")
                await conn.execute(update(User).where(User.id == user_id).values(email=corrected[role]))
        state["emails"] = corrected
        temporary = STATE.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temporary.replace(STATE)
        print("Updated existing demo email domains; user IDs and passwords unchanged")
    finally:
        await scoped.dispose()


async def cleanup():
    state = load_state()
    base, scoped = engines(state["schema"])
    try:
        async with base.begin() as conn:
            await assert_database(conn)
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{state["schema"]}" CASCADE'))
        async with base.connect() as conn:
            if await conn.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:name)"),
                                 {"name": state["schema"]}):
                raise RuntimeError("Demo schema cleanup did not complete")
        STATE.unlink()
        print("Demo schema and local state removed")
    finally:
        await scoped.dispose()
        await base.dispose()


def serve():
    import uvicorn

    state = load_state()
    _, scoped = engines(state["schema"])
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    async def demo_db():
        async with AsyncSession(scoped, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_db] = demo_db
    uvicorn.run(app, host="127.0.0.1", port=8123, log_level="warning")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "serve", "inspect", "upgrade", "repair-emails", "cleanup"))
    command = parser.parse_args().command
    if command == "serve":
        serve()
    else:
        asyncio.run({"prepare": prepare, "inspect": inspect, "upgrade": upgrade,
                     "repair-emails": repair_emails,
                     "cleanup": cleanup}[command]())
