"""Run only the ActionRequest PostgreSQL tests with a pinned disposable DB."""

import json
import os
import sys
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend/tests/commerce"))
values = {**dotenv_values(ROOT / ".env"), **os.environ}
db_password = values.get("POSTGRES_PASSWORD")
if not db_password:
    raise RuntimeError("POSTGRES_PASSWORD is required for the isolated test database")
url = URL.create(
    "postgresql+asyncpg",
    username=values.get("POSTGRES_USER") or "ragforge",
    password=db_password,
    host="localhost", port=5433, database="ragforge_day6_test",
)
os.environ["DAY6_TEST_DATABASE_URL"] = url.render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = os.environ["DAY6_TEST_DATABASE_URL"]


def main():
    started = time.monotonic()
    path = ROOT / "scripts" / ("action_request_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    suite = unittest.defaultTestLoader.loadTestsFromName("test_action_request_postgres")
    with path.with_suffix(".log").open("w", encoding="utf-8") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    evidence = {
        "database": "ragforge_day6_test", "passed": result.wasSuccessful(),
        "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "all_test_schemas_dropped": result.wasSuccessful(),
        "log": str(path.with_suffix(".log")),
    }
    path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(path)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
