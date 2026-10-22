"""Offline HTTP boundary tests; no pytest fixtures, real DB, or model clients."""

import json
import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.core_agent import CoreAgentError, CoreAgentResult
from app.ai.agents.investigation_report import evidence_contract, render_report, validate_report
from app.api.v1.router import api_router
from app.core.exceptions import register_exception_handlers
from app.core.security import create_access_token
from app.db.session import get_db
from app.middleware.request_context import RequestContextMiddleware


class InvestigationAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.org, self.other_org, self.case_id, self.user_id = (uuid4() for _ in range(4))
        self.user = SimpleNamespace(id=self.user_id, is_active=True)
        self.roles = {self.org: "member"}
        self.db = MagicMock(spec=AsyncSession)

        async def membership_query(statement):
            # Inspect the select expression without configuring unrelated ORM mappers.
            self.assertEqual(statement._raw_columns[0].name, "organization_members")
            filters = {condition.left.key: condition.right.value
                       for condition in statement._where_criteria}
            self.assertEqual(filters["user_id"], self.user_id)
            org = filters["organization_id"]
            member = (SimpleNamespace(organization_id=org, user_id=self.user_id, role=self.roles[org])
                      if org in self.roles else None)
            return SimpleNamespace(scalar_one_or_none=lambda: member)

        self.db.execute.side_effect = membership_query

        @asynccontextmanager
        async def separate_session():
            yield self.db
        self.start_patch("app.api.v1.endpoints.investigations.async_sessionmaker",
                         return_value=separate_session)
        async def reserve_stub(_db, **kwargs):
            now = datetime.now(UTC)
            return SimpleNamespace(id=uuid4(), as_of=kwargs["as_of"] or now,
                                   deadline_at=now + timedelta(seconds=690)), True
        self.reserve = self.start_patch("app.api.v1.endpoints.investigations.runs.reserve",
                                        new_callable=AsyncMock,
                                        side_effect=reserve_stub)
        self.finish = self.start_patch("app.api.v1.endpoints.investigations.runs.finish",
                                       new_callable=AsyncMock, return_value=True)

        async def offline_db():
            yield self.db

        # Real router, auth/role code, handlers and request IDs; no main lifespan or Redis middleware.
        app = FastAPI()
        register_exception_handlers(app)
        app.add_middleware(RequestContextMiddleware)
        app.include_router(api_router, prefix="/api/v1")
        app.dependency_overrides[get_db] = offline_db
        self.client = AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                                  base_url="http://offline")
        self.addAsyncCleanup(self.client.aclose)
        self.lookup = self.start_patch("app.services.auth_service.user_service.get_user_by_id",
                                      new_callable=AsyncMock, return_value=self.user)
        self.provider = object()
        self.factory = self.start_patch("app.api.v1.endpoints.investigations.get_llm_provider",
                                       return_value=self.provider)
        self.agent = self.start_patch("app.api.v1.endpoints.investigations.run_core_agent",
                                     new_callable=AsyncMock, return_value=self.result("insufficient_evidence"))
        self.token = create_access_token(subject=str(self.user_id), organization_id=str(self.org))

    def start_patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def result(self, outcome):
        if outcome == "not_found":
            trace = [{"tool": "get_exception_case", "result": {"status": "not_found"}}]
        else:
            trace = [{"tool": "analyze_fulfillment", "result": {"status": "found", "analysis": {
                "as_of": "2026-10-09T12:00:00+00:00", "shipment": {"status": "unknown"},
                "delivery": {"status": "unknown"}, "evidence_event_ids": []}}}]
        report = validate_report(json.dumps(evidence_contract(trace)), trace)
        return CoreAgentResult(render_report(report, trace), trace, 2, report.model_dump(mode="json"),
                               "PRIVATE_MODEL_RESPONSE", [{"content": "PRIVATE_PROMPT"}])

    async def post(self, *, org=None, body=None, token=None, extra_headers=None):
        headers = {"Authorization": f"Bearer {token or self.token}", **(extra_headers or {})}
        return await self.client.post(f"/api/v1/organizations/{org or self.org}/investigations",
                                      json=body if body is not None else {"case_id": str(self.case_id)},
                                      headers=headers)

    async def asyncTearDown(self):
        self.db.add.assert_not_called()
        self.db.delete.assert_not_awaited()
        self.db.flush.assert_not_awaited()
        self.db.commit.assert_not_awaited()

    async def test_duplicate_running_submission_returns_status_without_second_model_call(self):
        now = datetime.now(UTC)
        run = SimpleNamespace(
            id=uuid4(), organization_id=self.org, requested_by_user_id=self.user_id,
            case_id=self.case_id, workspace_id=None, as_of=now, status="running",
            deadline_at=now + timedelta(seconds=690), created_at=now,
            finished_at=None, error_code=None, response=None,
        )
        self.reserve.side_effect = None
        self.reserve.return_value = (run, False)
        self.start_patch("app.api.v1.endpoints.investigations.runs.expire",
                         new_callable=AsyncMock)
        self.start_patch("app.api.v1.endpoints.investigations.runs.authorized_run",
                         new_callable=AsyncMock, return_value=run)
        response = await self.post(extra_headers={"Idempotency-Key": "same-submission"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "running")
        self.assertEqual(response.json()["id"], str(run.id))
        self.assertIsNone(response.json()["result"])
        self.agent.assert_not_awaited()
        self.factory.assert_not_called()

    async def test_duplicate_saved_report_uses_original_validated_response(self):
        now = datetime.now(UTC)
        original = {"run_id": str(uuid4()), "request_id": str(uuid4()),
                    "organization_id": str(self.org), "case_id": str(self.case_id),
                    "as_of": now.isoformat(), "report": self.agent.return_value.report,
                    "handoff": self.agent.return_value.answer, "observations": None}
        run = SimpleNamespace(id=UUID(original["run_id"]), organization_id=self.org,
                              requested_by_user_id=self.user_id, case_id=self.case_id,
                              workspace_id=None, as_of=now, status="succeeded",
                              deadline_at=now + timedelta(seconds=690), created_at=now,
                              finished_at=now, error_code=None, response=original)
        self.reserve.side_effect = None
        self.reserve.return_value = (run, False)
        self.start_patch("app.api.v1.endpoints.investigations.runs.expire",
                         new_callable=AsyncMock)
        self.start_patch("app.api.v1.endpoints.investigations.runs.authorized_run",
                         new_callable=AsyncMock, return_value=run)
        response = await self.post(extra_headers={"Idempotency-Key": "same-submission"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["request_id"], original["request_id"])
        self.assertEqual(response.json()["report"], original["report"])
        self.agent.assert_not_awaited()

    async def test_missing_invalid_or_inactive_login_rejected(self):
        response = await self.client.post(f"/api/v1/organizations/{self.org}/investigations",
                                          json={"case_id": str(self.case_id)})
        self.assertEqual(response.status_code, 401)
        for token in ("invalid-token", create_access_token(subject=str(self.user_id),
                                                          extra_claims={"type": "refresh"})):
            with self.subTest(token_type=token == "invalid-token"):
                self.assertEqual((await self.post(token=token)).status_code, 401)
        self.user.is_active = False
        self.assertEqual((await self.post()).status_code, 401)
        self.db.execute.assert_not_awaited()
        self.agent.assert_not_awaited()
        self.factory.assert_not_called()

    async def test_other_org_denied_even_if_token_or_header_claims_it(self):
        claimed = create_access_token(subject=str(self.user_id), organization_id=str(self.other_org))
        response = await self.post(org=self.other_org, token=claimed,
                                   extra_headers={"X-Organization-ID": str(self.other_org)})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "permission_denied")
        self.db.execute.assert_awaited_once()
        self.agent.assert_not_awaited()
        self.factory.assert_not_called()

    async def test_unrecognized_membership_role_denied(self):
        self.roles[self.org] = "unknown-role"
        self.assertEqual((await self.post()).status_code, 403)
        self.agent.assert_not_awaited()
        self.factory.assert_not_called()

    async def test_membership_database_failure_is_not_not_found_or_success(self):
        self.db.execute.side_effect = RuntimeError("PRIVATE_DATABASE_CONNECTION")
        response = await self.post()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "internal_error")
        self.assertNotIn("report", response.json())
        self.assertNotIn("PRIVATE_", response.text)
        self.agent.assert_not_awaited()
        self.factory.assert_not_called()

    async def test_multi_org_selection_requires_membership_and_passes_verified_context(self):
        self.roles[self.other_org] = "member"
        response = await self.post(org=self.other_org, body={"case_id": str(self.case_id),
            "as_of": "2026-10-09T20:00:00+08:00"}, extra_headers={"X-Organization-ID": str(self.org)})
        self.assertEqual(response.status_code, 200)
        self.lookup.assert_awaited_once_with(self.db, self.user_id)
        self.agent.assert_awaited_once_with(self.provider, self.db, organization_id=self.other_org,
            case_id=self.case_id, as_of=datetime(2026, 10, 9, 12, tzinfo=UTC))
        self.assertEqual(response.json()["organization_id"], str(self.other_org))
        self.assertEqual(response.json()["as_of"], "2026-10-09T12:00:00Z")

    async def test_invalid_parameters_and_body_org_injection_do_not_call_agent(self):
        for body in ({}, {"case_id": "invalid"},
                     {"case_id": str(self.case_id), "as_of": "2026-10-09T12:00:00"},
                     {"case_id": str(self.case_id), "as_of": "invalid"},
                     {"case_id": str(self.case_id), "organization_id": str(self.other_org)}):
            with self.subTest(body=body):
                response = await self.post(body=body)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], "validation_error")
        self.assertEqual((await self.post(org="invalid")).status_code, 422)
        self.agent.assert_not_awaited()
        self.factory.assert_not_called()
        self.db.execute.assert_not_awaited()

    async def test_default_time_request_id_and_public_report_projection(self):
        analysis = self.agent.return_value.trace[0]["result"]["analysis"]
        analysis.update({
            "whole_order_completion": "unknown",
            "shipment": {
                "status": "late", "scope": "shipment", "tracking_number": "TRACK-1",
                "expected_at": "2026-10-09T10:00:00Z",
                "actual_at": "2026-10-09T11:00:00Z",
                "difference_seconds": 3600, "reason": None,
                "prompt": "PRIVATE_PROMPT_IN_TOOL_RESULT",
            },
            "delivery": {"status": "unknown"},
            "internal_error": "PRIVATE_INTERNAL_ERROR",
            "trace": "PRIVATE_TRACE",
        })
        # Keep the controlled Core result internally consistent: the public
        # boundary now verifies the report against its observation before saving.
        trace = self.agent.return_value.trace
        verified = validate_report(json.dumps(evidence_contract(trace)), trace)
        self.agent.return_value = CoreAgentResult(
            render_report(verified, trace), trace, 2, verified.model_dump(mode="json"),
            "PRIVATE_MODEL_RESPONSE", [{"content": "PRIVATE_PROMPT"}],
        )
        before = datetime.now(UTC)
        response = await self.post()
        after = datetime.now(UTC)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        cutoff = self.agent.call_args.kwargs["as_of"]
        self.assertLessEqual(before, cutoff)
        self.assertLessEqual(cutoff, after)
        self.assertEqual(cutoff.utcoffset(), timedelta(0))
        self.assertEqual(body["request_id"], response.headers["X-Request-ID"])
        UUID(body["request_id"])
        UUID(body["run_id"])
        self.assertEqual(set(body), {"run_id", "request_id", "organization_id", "case_id", "as_of",
                                     "report", "handoff", "observations"})
        observations = body["observations"]
        self.assertEqual(set(observations), {"whole_order_completion", "shipment", "delivery", "allocation"})
        self.assertEqual(observations["whole_order_completion"], "unknown")
        self.assertIsNone(observations["allocation"])
        timing_fields = {"status", "scope", "tracking_number", "expected_at", "actual_at",
                         "difference_seconds", "reason"}
        self.assertEqual(set(observations["shipment"]), timing_fields)
        self.assertEqual(observations["shipment"], {
            "status": "late", "scope": "shipment", "tracking_number": "TRACK-1",
            "expected_at": "2026-10-09T10:00:00Z",
            "actual_at": "2026-10-09T11:00:00Z",
            "difference_seconds": 3600.0, "reason": None,
        })
        self.assertEqual(set(observations["delivery"]), timing_fields)
        self.assertEqual(observations["delivery"], {
            "status": "unknown", "scope": None, "tracking_number": None,
            "expected_at": None, "actual_at": None,
            "difference_seconds": None, "reason": None,
        })
        self.assertEqual(body["report"], self.agent.return_value.report)
        self.assertEqual(body["handoff"], self.agent.return_value.answer)
        self.assertIn("6. 处理状态", body["handoff"])
        self.assertNotIn("PRIVATE_", response.text)
        for internal in ("trace", "prompt", "internal_error", "model_response"):
            self.assertNotIn(internal, body)
            self.assertNotIn(internal, observations)
            self.assertNotIn(internal, observations["shipment"])
        self.assertEqual(body["case_id"], str(self.case_id))

    async def test_linked_allocation_observation_is_scoped_public_projection(self):
        failure_id, attribution_id = str(uuid4()), str(uuid4())
        trace = [{"tool": "analyze_fulfillment", "result": {"status": "found", "analysis": {
            "as_of": "2026-10-09T12:00:00Z", "whole_order_completion": "unknown",
            "evidence_event_ids": [failure_id, attribution_id],
            "shipment": {"status": "late", "scope": "shipment"},
            "delivery": {"status": "unknown"},
            "allocation": {
                "status": "blocked", "causal_status": "linked_to_shipment_delay",
                "failure_event_ids": [failure_id], "attribution_event_id": attribution_id,
                "linked_failure_event_id": failure_id,
                "failures": [{"event_id": failure_id, "secret": "PRIVATE_SOURCE"}],
            },
        }}}]
        report = validate_report(json.dumps(evidence_contract(trace)), trace)
        self.agent.return_value = CoreAgentResult(
            render_report(report, trace), trace, 2, report.model_dump(mode="json"),
            "PRIVATE_MODEL_RESPONSE", [{"content": "PRIVATE_PROMPT"}],
        )
        response = await self.post()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["report"]["root_cause"], "inventory_allocation_blocked")
        self.assertEqual(body["observations"]["allocation"], {
            "status": "blocked", "causal_status": "linked_to_shipment_delay",
            "failure_event_ids": [failure_id], "attribution_event_id": attribution_id,
            "linked_failure_event_id": failure_id,
        })
        self.assertNotIn("PRIVATE_", response.text)

    async def test_not_found_and_insufficient_evidence_are_completed_reports(self):
        for outcome in ("not_found", "insufficient_evidence"):
            with self.subTest(outcome=outcome):
                self.agent.return_value = self.result(outcome)
                response = await self.post()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["report"]["outcome"], outcome)
                self.assertEqual(response.json()["report"]["root_cause"], "unknown")
                self.assertNotIn("error", response.json())

    async def test_execution_failures_are_not_success_or_not_found_and_are_sanitized(self):
        for code in ("tool_failed", "tool_timeout", "model_failed", "ungrounded_final"):
            with self.subTest(code=code):
                self.agent.side_effect = CoreAgentError("PRIVATE_CONNECTION_STRING", error_code=code,
                                                       trace=[{"internal": "PRIVATE_PROMPT"}])
                response = await self.post()
                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assertNotIn("report", response.json())
                self.assertNotIn("PRIVATE_", response.text)
                self.assertIn("X-Request-ID", response.headers)
        self.agent.side_effect = RuntimeError("PRIVATE_CONNECTION_STRING")
        response = await self.post()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "core_agent_error")
        self.assertNotIn("PRIVATE_", response.text)

    async def test_failure_that_did_not_update_a_run_reconciles_its_deadline(self):
        self.agent.side_effect = CoreAgentError("PRIVATE_FAILURE", error_code="model_failed")
        self.finish.return_value = False
        reconcile = self.start_patch("app.api.v1.endpoints.investigations.runs.expire",
                                     new_callable=AsyncMock)
        response = await self.post()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "model_failed")
        self.finish.assert_awaited_once()
        self.assertEqual(self.finish.await_args.kwargs, {"error_code": "model_failed"})
        reconcile.assert_awaited_once()
        self.assertNotIn("PRIVATE_", response.text)

    async def test_unexpected_failure_with_no_terminal_write_also_reconciles(self):
        self.factory.side_effect = RuntimeError("PRIVATE_PROVIDER_CONFIG")
        self.finish.return_value = False
        reconcile = self.start_patch("app.api.v1.endpoints.investigations.runs.expire",
                                     new_callable=AsyncMock)
        response = await self.post()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "core_agent_error")
        self.finish.assert_awaited_once()
        reconcile.assert_awaited_once()
        self.assertNotIn("PRIVATE_", response.text)

    async def test_provider_construction_failure_is_sanitized(self):
        self.factory.side_effect = RuntimeError("PRIVATE_PROVIDER_CONFIG")
        response = await self.post()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("PRIVATE_", response.text)
        self.agent.assert_not_awaited()

    def enable_workspace(self, *, role="viewer", organization_id=None):
        workspace_id = uuid4()
        self.db.get.return_value = SimpleNamespace(
            id=workspace_id, organization_id=organization_id or self.org,
        )
        organization_query = self.db.execute.side_effect

        async def membership_query(statement):
            if statement._raw_columns[0].name == "organization_members":
                return await organization_query(statement)
            self.assertEqual(statement._raw_columns[0].name, "workspace_members")
            filters = {c.left.key: c.right.value for c in statement._where_criteria}
            self.assertEqual(filters, {"workspace_id": workspace_id, "user_id": self.user_id})
            value = SimpleNamespace(workspace_id=workspace_id, user_id=self.user_id, role=role) if role else None
            return SimpleNamespace(scalar_one_or_none=lambda: value)

        self.db.execute.side_effect = membership_query
        return workspace_id

    async def test_optional_workspace_passes_only_verified_context(self):
        workspace = self.enable_workspace()
        response = await self.post(body={"case_id": str(self.case_id), "workspace_id": str(workspace)})
        self.assertEqual(response.status_code, 200)
        context = self.agent.await_args.kwargs
        self.assertEqual(context["organization_id"], self.org)
        self.assertEqual(context["user_id"], self.user_id)
        self.assertEqual(context["workspace_id"], workspace)

    async def test_required_lookup_passes_only_authorized_context(self):
        workspace = self.enable_workspace()
        response = await self.post(body={"case_id": str(self.case_id), "workspace_id": str(workspace),
                                         "require_knowledge": True})
        self.assertEqual(response.status_code, 200)
        context = self.agent.await_args.kwargs
        self.assertIs(context["require_knowledge"], True)
        self.assertEqual(context["organization_id"], self.org)
        self.assertEqual(context["user_id"], self.user_id)
        self.assertEqual(context["workspace_id"], workspace)

    async def test_required_lookup_without_scope_or_non_boolean_never_calls_agent(self):
        for extra in ({"require_knowledge": True},
                      {"workspace_id": str(uuid4()), "require_knowledge": "true"}):
            response = await self.post(body={"case_id": str(self.case_id), **extra})
            self.assertEqual(response.status_code, 422)
        self.agent.assert_not_awaited()
        self.factory.assert_not_called()
        self.db.execute.assert_not_awaited()

    async def test_required_lookup_does_not_bypass_workspace_permission(self):
        workspace = self.enable_workspace(role=None)
        response = await self.post(body={"case_id": str(self.case_id), "workspace_id": str(workspace),
                                         "require_knowledge": True})
        self.assertEqual(response.status_code, 403)
        self.agent.assert_not_awaited()
        self.factory.assert_not_called()

    async def test_workspace_without_membership_is_rejected_before_agent(self):
        workspace = self.enable_workspace(role=None)
        response = await self.post(body={"case_id": str(self.case_id), "workspace_id": str(workspace)})
        self.assertEqual(response.status_code, 403)
        self.agent.assert_not_awaited()
        self.factory.assert_not_called()

    async def test_other_organization_workspace_is_rejected_before_agent(self):
        workspace = self.enable_workspace(organization_id=self.other_org)
        response = await self.post(body={"case_id": str(self.case_id), "workspace_id": str(workspace)})
        self.assertEqual(response.status_code, 403)
        self.agent.assert_not_awaited()

    async def test_missing_workspace_is_denied_not_business_not_found(self):
        workspace = self.enable_workspace()
        self.db.get.return_value = None
        response = await self.post(body={"case_id": str(self.case_id), "workspace_id": str(workspace)})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("report", response.json())
        self.agent.assert_not_awaited()

    async def test_invalid_workspace_or_user_injection_never_calls_agent(self):
        for extra in ({"workspace_id": "invalid"}, {"user_id": str(uuid4())}):
            response = await self.post(body={"case_id": str(self.case_id), **extra})
            self.assertEqual(response.status_code, 422)
        self.agent.assert_not_awaited()
        self.db.execute.assert_not_awaited()

    async def test_workspace_query_fault_is_not_no_matches_or_success(self):
        workspace = self.enable_workspace()
        self.db.get.side_effect = RuntimeError("PRIVATE_CONNECTION")
        response = await self.post(body={"case_id": str(self.case_id), "workspace_id": str(workspace)})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("report", response.json())
        self.assertNotIn("PRIVATE_CONNECTION", response.text)
        self.agent.assert_not_awaited()
