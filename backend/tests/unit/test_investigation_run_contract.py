"""Offline submission identity and public result contract checks."""

import unittest
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.services.investigation_run_service import finish, request_hash


class InvestigationRunContractTests(unittest.TestCase):
    def test_request_hash_normalizes_time_but_distinguishes_submitted_parameters(self):
        case, workspace = uuid4(), uuid4()
        point = datetime(2026, 10, 22, 12, tzinfo=UTC)
        base = dict(case_id=case, as_of=point, workspace_id=workspace,
                    require_knowledge=True)
        fingerprint = request_hash(**base)
        self.assertEqual(fingerprint, request_hash(**{
            **base, "as_of": point.astimezone(timezone(timedelta(hours=8))),
        }))
        for change in ({"case_id": uuid4()}, {"as_of": None},
                       {"workspace_id": uuid4()}, {"require_knowledge": False}):
            with self.subTest(change=change):
                self.assertNotEqual(fingerprint, request_hash(**{**base, **change}))


class InvestigationRunFinishContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_uses_sql_null_while_success_keeps_deadline_guard(self):
        self.assertIn("investigation_runs", Base.metadata.tables)
        run_id = uuid4()
        db = MagicMock(spec=AsyncSession)
        db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: run_id))
        db.commit = AsyncMock()

        self.assertTrue(await finish(db, run_id, error_code="model_failed"))
        failure_sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
        self.assertIn("response=NULL", failure_sql.replace(" ", ""))
        self.assertNotIn("deadline_at >", failure_sql)

        self.assertTrue(await finish(db, run_id, response={"report": "verified"}))
        success_sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
        self.assertIn("deadline_at >", success_sql)
        self.assertNotIn("response=NULL", success_sql.replace(" ", ""))
        self.assertEqual(db.commit.await_count, 2)
