"""Run only investigation lifecycle tests in the guarded local PostgreSQL DB."""

import asyncio
import os
import sys
import unittest
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend/tests/commerce"))

password = os.environ.get("POSTGRES_PASSWORD")
username = os.environ.get("POSTGRES_USER")
if not username or not password:
    raise RuntimeError("Existing PostgreSQL container credentials are required in process memory")
url = URL.create("postgresql+asyncpg", username=username, password=password,
                 host="localhost", port=5433, database="ragforge_day6_test")
os.environ["DAY6_TEST_DATABASE_URL"] = url.render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = os.environ["DAY6_TEST_DATABASE_URL"]


async def preflight() -> None:
    """Fail once, before test setup, if the isolated database is inaccessible."""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            if await connection.scalar(text("SELECT current_database()")) != "ragforge_day6_test":
                raise RuntimeError("Unexpected database identity")
    except Exception as exc:  # noqa: BLE001 -- never print a credential-bearing connection error
        raise RuntimeError(f"Isolated PostgreSQL preflight failed: {type(exc).__name__}") from None
    finally:
        await engine.dispose()


asyncio.run(preflight())
test_name = "test_investigation_runs_postgres"
if len(sys.argv) == 2 and sys.argv[1] == "test_failure_deadline_and_unsaved_report":
    test_name += ".InvestigationRunsPostgresTests." + sys.argv[1]
elif len(sys.argv) != 1:
    raise RuntimeError("Only the guarded lifecycle method may be selected")
suite = unittest.defaultTestLoader.loadTestsFromName(test_name)
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
