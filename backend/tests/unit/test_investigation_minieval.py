"""Offline checks for the local one-attempt evaluation harness."""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import investigation_minieval_once as subject  # noqa: E402

from app.ai.agents.investigation_report import evidence_contract, render_report, validate_report  # noqa: E402


class MiniEvalOfflineTests(unittest.TestCase):
    def test_b2_reuses_b_fixture_but_has_distinct_one_attempt_evidence(self):
        state = {"database": "ragforge_day6_test", "prepared": True,
                 "organization_id": "org", "user_id": "member", "collection": "collection",
                 "case_id": "case", "workspace_id": "workspace", "as_of": "old"}
        with (patch.object(subject.page, "state_read", return_value=state),
              patch.object(subject.demo, "load_state", return_value={
                  "organization_id": "org", "member_id": "member"}),
              patch.object(subject.page, "configure")):
            fixture = subject.fixture("B2")
        self.assertEqual(fixture["as_of"], subject.B_AS_OF)
        self.assertEqual(fixture["case_id"], state["case_id"])
        self.assertEqual(subject.EXPECTED["B2"], subject.EXPECTED["B"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            original = root / "scripts/investigation_minieval_B_once.json"
            original.write_text("original B failure", encoding="utf-8")
            with patch.object(subject, "ROOT", root):
                evidence = subject.Evidence("B2", fixture)
                self.assertEqual(evidence.snapshot.name, "investigation_minieval_B2_once.json")
                self.assertTrue(evidence.events.exists())
                self.assertTrue(evidence.data["submission_key"].startswith("minieval-b2-"))
                self.assertEqual(original.read_text(encoding="utf-8"), "original B failure")
                with self.assertRaises(FileExistsError):
                    subject.Evidence("B2", fixture)

    def test_b2_stale_attempt_marker_blocks_before_preflight_or_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts/investigation_minieval_B2_once.active").write_text("retained")
            with (patch.object(subject, "ROOT", root),
                  patch.object(subject, "fixture") as fixture,
                  patch.object(subject, "preflight", new_callable=AsyncMock) as preflight,
                  self.assertRaises(subject.PreflightError)):
                subject.asyncio.run(subject.run("B2"))
            fixture.assert_not_called()
            preflight.assert_not_awaited()

    def test_repair_b_cli_cannot_dispatch_model_run(self):
        with (patch.object(sys, "argv", ["minieval", "repair-b"]),
              patch.object(subject, "repair_b_events", new_callable=AsyncMock,
                           return_value={"migration": "0008_order_allocation_evidence"}) as repair,
              patch.object(subject, "run", new_callable=AsyncMock) as run,
              patch("sys.stdout", new_callable=io.StringIO)):
            subject.main()
        repair.assert_awaited_once_with()
        run.assert_not_awaited()

    def test_repair_b_rejects_wrong_schema_before_database_access(self):
        with (patch.object(subject.page, "state_read", return_value={
                  "database": "ragforge_day6_test", "schema": "other_schema",
                  "case_id": "59db2e27-ac93-4ef0-b939-a72ac2b5113a", "prepared": True}),
              patch.object(subject.demo, "engines") as engines,
              self.assertRaises(subject.PreflightError)):
            subject.asyncio.run(subject.repair_b_events())
        engines.assert_not_called()

    def test_event_schema_requires_full_0008_surface(self):
        def row(**values):
            return SimpleNamespace(**values)

        class Result:
            def __init__(self, values):
                self.values = values

            def all(self):
                return self.values

        class Connection:
            def __init__(self, *, upgraded=False, partial=False):
                self.upgraded, self.partial = upgraded, partial

            async def execute(self, statement):
                sql = str(statement)
                if "information_schema.columns" in sql:
                    columns = [row(column_name=name, data_type=kind, is_nullable=nullable)
                               for name, (kind, nullable) in subject.EVENT_COLUMNS.items()]
                    if self.upgraded or self.partial:
                        columns.append(row(column_name="caused_by_event_id", data_type="uuid",
                                           is_nullable="YES"))
                    return Result(columns)
                if "FROM pg_constraint" in sql:
                    self.assert_constraint_type_is_text(sql)
                    constraints = [row(conname=name, contype="c", definition="CHECK (value)")
                                   for name in subject.EVENT_BASE_CHECKS]
                    for item in constraints:
                        if item.conname == "ck_fulfillment_events_type":
                            item.definition += (" inventory_allocation_failed shipment_delay_attributed"
                                                if self.upgraded else " shipment_promised")
                    if self.upgraded:
                        constraints.extend([
                            row(conname="fk_fulfillment_events_causal_reference", contype="f",
                                definition="FOREIGN KEY (caused_by_event_id) REFERENCES fulfillment_events(id) ON DELETE RESTRICT"),
                            row(conname="ck_fulfillment_events_causal_reference", contype="c",
                                definition="CHECK (caused_by_event_id IS NOT NULL)"),
                            row(conname="ck_fulfillment_events_allocation_provenance", contype="c",
                                definition="CHECK (external_event_id IS NOT NULL AND tracking_number IS NOT NULL)"),
                        ])
                    return Result(constraints)
                indexes = [row(indexname=name, indexdef=(
                    "CREATE " + ("UNIQUE " if name.startswith("uq_") else "")
                    + "INDEX " + name + " ON fulfillment_events (" + ", ".join(fields) + ")"
                    + (" WHERE (external_event_id IS NOT NULL)" if name.startswith("uq_") else "")))
                    for name, fields in subject.EVENT_INDEXES.items()]
                return Result(indexes)

            @staticmethod
            def assert_constraint_type_is_text(sql):
                if "contype::text AS contype" not in sql:
                    raise AssertionError("Constraint type must be normalized from pg_catalog char")

        self.assertEqual(subject.asyncio.run(subject.event_schema_state(Connection())), "before_0008")
        self.assertEqual(subject.asyncio.run(subject.event_schema_state(Connection(upgraded=True))),
                         "current_0008")
        with self.assertRaises(subject.PreflightError):
            subject.asyncio.run(subject.event_schema_state(Connection(partial=True)))

    def test_upgrade_b_cli_cannot_dispatch_model_run(self):
        with (patch.object(sys, "argv", ["minieval", "upgrade-b"]),
              patch.object(subject, "upgrade_b_runs", new_callable=AsyncMock,
                           return_value={"migration": "0009_investigation_runs"}) as upgrade,
              patch.object(subject, "run", new_callable=AsyncMock) as run,
              patch("sys.stdout", new_callable=io.StringIO)):
            subject.main()
        upgrade.assert_awaited_once_with()
        run.assert_not_awaited()

    def test_upgrade_b_rejects_wrong_retained_schema_before_database_access(self):
        with (patch.object(subject.page, "state_read", return_value={
                  "database": "ragforge_day6_test", "schema": "other_schema",
                  "case_id": "59db2e27-ac93-4ef0-b939-a72ac2b5113a", "prepared": True}),
              patch.object(subject.demo, "engines") as engines,
              self.assertRaises(subject.PreflightError)):
                subject.asyncio.run(subject.upgrade_b_runs())
        engines.assert_not_called()

    def test_preflight_cli_never_dispatches_model_run(self):
        with (patch.object(sys, "argv", ["minieval", "preflight", "--case", "C"]),
              patch.object(subject, "preflight", new_callable=AsyncMock,
                           return_value={"case_key": "C"}) as ready,
              patch.object(subject, "run", new_callable=AsyncMock) as run,
              patch("sys.stdout", new_callable=io.StringIO)):
            subject.main()
        ready.assert_awaited_once_with("C")
        run.assert_not_awaited()

    def test_one_attempt_marker_never_overwrites_existing_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            with patch.object(subject, "ROOT", root):
                state = {"case_id": str(subject.ABSENT_CASE_ID), "organization_id": "org",
                         "workspace_id": "workspace", "as_of": "2026-10-20T00:00:00Z"}
                evidence = subject.Evidence("C", state)
                evidence.emit("model_completed", phase="report", index=2,
                              elapsed_seconds=0.1, raw_candidate='{"outcome":"not_found"}')
                before = evidence.snapshot.read_bytes()
                with self.assertRaises(FileExistsError):
                    subject.Evidence("C", state)
                self.assertEqual(evidence.snapshot.read_bytes(), before)
                self.assertIn("model_completed", evidence.events.read_text(encoding="utf-8"))

    def test_original_validator_classifies_first_and_corrected_report(self):
        trace = [{"tool": "get_exception_case", "result": {"status": "not_found"}}]
        expected = evidence_contract(trace)
        report = validate_report(json.dumps(expected), trace)
        body = {"report": report.model_dump(mode="json"),
                "handoff": render_report(report, trace)}
        self.assertEqual(subject.classify("C", body, trace, []), "first_answer_pass")
        self.assertEqual(subject.classify("C", body, trace,
                                          [{"phase": "report", "reason": "invalid_evidence_report"}]),
                         "corrected_pass")
        bad = {"report": {**body["report"], "root_cause": "inventory_allocation_blocked"},
               "handoff": body["handoff"]}
        with self.assertRaises(ValueError):
            subject.classify("C", bad, trace, [])


if __name__ == "__main__":
    unittest.main()
