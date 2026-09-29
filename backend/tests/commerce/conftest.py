"""Commerce-only tests, independent of app startup and the global DB fixtures.

Run from backend with: python -m pytest --confcutdir=tests/commerce tests/commerce
Database tests require COMMERCE_TEST_DATABASE_URL pointing explicitly at a
disposable PostgreSQL database whose name ends in _test. DATABASE_URL is never
used here. Each test creates a random private schema and rolls back all DDL/data.
"""

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import MetaData, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.db.base import Base

COMMERCE_TABLES = ("products", "orders", "order_items", "return_requests", "refunds")
MIGRATION_PATH = Path(__file__).resolve().parents[2] / "alembic/versions/0002_commerce_core.py"


@pytest.fixture(scope="session")
def commerce_migration():
    spec = importlib.util.spec_from_file_location("commerce_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest_asyncio.fixture(params=["models", "migration"])
async def commerce_connection(request, commerce_migration):
    raw_url = os.environ.get("COMMERCE_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("No explicit disposable COMMERCE_TEST_DATABASE_URL; no database connection made")
    url = make_url(raw_url)
    if url.drivername != "postgresql+asyncpg" or not (url.database or "").endswith("_test"):
        pytest.fail("Commerce tests require postgresql+asyncpg and a database name ending in _test")

    engine = create_async_engine(url)
    schema = f"commerce_test_{uuid.uuid4().hex}"
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))

                def setup(sync_connection):
                    metadata = MetaData()
                    Base.metadata.tables["organizations"].to_metadata(metadata)
                    if request.param == "models":
                        for name in COMMERCE_TABLES:
                            Base.metadata.tables[name].to_metadata(metadata)
                        metadata.create_all(sync_connection)
                    else:
                        metadata.create_all(sync_connection)
                        with Operations.context(MigrationContext.configure(sync_connection)):
                            commerce_migration.upgrade()

                await connection.run_sync(setup)
                yield connection
            finally:
                # PostgreSQL transactional DDL removes even the private schema.
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory():
    # Keep ORM commits inside a SAVEPOINT so the outer test transaction survives.
    return lambda connection: Session(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
