"""Read-tool contracts without global fixtures."""
import json
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools import investigation_tools as subject
from app.core.exceptions import NotFoundError, ValidationAppError

NOW = datetime(2026, 10, 11, tzinfo=UTC)


class InvestigationToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_analysis_preserves_investigation_lead_without_full_event_detail(self):
        db = MagicMock(spec=AsyncSession)
        org, order, event = uuid4(), uuid4(), uuid4()
        tool = subject.create_analyze_fulfillment_tool(db, organization_id=org)
        analysis = {"evidence_event_ids": [event], "shipment": {"status": "unknown"}, "timeline": [
            {"event_id": event, "event_type": "shipment_promised",
             "description": "Reservation pending; SKU=Sku-A;"},
            {"event_id": uuid4(), "event_type": "in_transit", "description": "Full warehouse detail"},
        ]}
        with patch("app.ai.tools.investigation_tools.fulfillment_service.analyze_fulfillment",
                   new_callable=AsyncMock, return_value=analysis):
            result = await tool.ainvoke({"order_id": str(order), "as_of": NOW.isoformat()})
        self.assertEqual(result["analysis"]["promise_notes"], [
            {"event_id": str(event), "description": "Reservation pending; SKU=Sku-A;"},
        ])
        self.assertNotIn("Full warehouse detail", json.dumps(result))
        self.assertIn("timeline", analysis)  # Service result is not mutated.

    def setUp(self):
        self.db = MagicMock(spec=AsyncSession)
        self.org, self.identifier = uuid4(), uuid4()
        self.tools = subject.create_investigation_tools(self.db, organization_id=self.org)
        self.inputs = [
            {"case_id": str(self.identifier)},
            {"order_id": str(self.identifier), "as_of": NOW.isoformat()},
            {"sku": " SKU-A "},
            {"order_id": str(self.identifier)},
        ]
        self.services = [
            "exception_service.get_exception_case", "fulfillment_service.analyze_fulfillment",
            "inventory_service.get_inventory_status", "fulfillment_service.get_fulfillment_events",
        ]

    async def test_schema_context_and_invalid_inputs_never_call_service(self):
        for tool, arguments, service in zip(self.tools, self.inputs, self.services, strict=True):
            with patch.object(self.db, "execute", new_callable=AsyncMock) as execute:
                schema = tool.get_input_schema().model_json_schema()
                self.assertFalse(schema["additionalProperties"])
                self.assertNotIn("organization_id", tool.tool_call_schema.model_json_schema()["properties"])
                variants = [{**arguments, key: "spoof"} for key in ("organization_id", "db")]
                key = "sku" if "sku" in arguments else next(iter(arguments))
                variants += [{**arguments, key: value} for value in ("", " ", 123, None)]
                if "sku" in arguments:
                    variants.append({"sku": "x" * 129})
                if "order_id" in arguments:
                    variants.append({**arguments, "as_of": "2026-10-11T00:00:00"})
                with patch("app.ai.tools.investigation_tools." + service, new_callable=AsyncMock) as call:
                    for values in variants:
                        with self.subTest(tool=tool.name, values=values), self.assertRaises(ValidationError):
                            await tool.ainvoke(values)
                    call.assert_not_awaited()
                execute.assert_not_awaited()

    async def test_service_calls_serialization_and_whitelisted_case(self):
        case = SimpleNamespace(
            id=self.identifier, order_id=self.identifier, exception_type="other", status="open",
            problem_description="Investigate", conclusion=None, evidence_event_ids=[self.identifier],
            opened_at=NOW, closed_at=None, secret="hidden", _sa_instance_state="hidden",
        )
        values = [case, {"as_of": NOW, "evidence_event_ids": [self.identifier]},
                  {"observed_at": NOW, "available_quantity": -3}, []]
        expected = [dict(case_id=self.identifier), dict(order_id=self.identifier, as_of=NOW),
                    dict(sku="SKU-A"), dict(order_id=self.identifier, as_of=None)]
        for tool, arguments, service, value, kwargs in zip(
            self.tools, self.inputs, self.services, values, expected, strict=True,
        ):
            with patch("app.ai.tools.investigation_tools." + service, new_callable=AsyncMock) as call:
                call.return_value = value
                result = await tool.ainvoke(arguments)
                call.assert_awaited_once_with(self.db, organization_id=self.org, **kwargs)
                self.assertEqual(result["status"], "found")
                encoded = json.dumps(result)
                self.assertNotIn("hidden", encoded)
                if tool.name == "get_inventory_status":
                    self.assertEqual(result["inventory"]["available_quantity"], -3)
                    self.assertEqual(result["inventory"]["observed_at"], NOW.isoformat())
                if tool.name == "get_exception_case":
                    self.assertEqual(result["case"]["evidence_event_ids"], [str(self.identifier)])

    async def test_domain_errors_and_execution_failures_are_distinct(self):
        for tool, arguments, service in zip(self.tools, self.inputs, self.services, strict=True):
            for error, status in ((NotFoundError("Missing"), "not_found"),
                                  (ValidationAppError("Invalid"), "invalid_input")):
                with patch("app.ai.tools.investigation_tools." + service, new_callable=AsyncMock) as call:
                    call.side_effect = error
                    result = await tool.ainvoke(arguments)
                    self.assertEqual(result["status"], status)
                    self.assertEqual(result["error_code"], error.error_code)
            for error in (TimeoutError("timeout"), ConnectionError("offline"), RuntimeError("SQL failure")):
                with patch("app.ai.tools.investigation_tools." + service, new_callable=AsyncMock) as call:
                    call.side_effect = error
                    with self.assertRaises(type(error)) as caught:
                        await tool.ainvoke(arguments)
                    self.assertIs(caught.exception, error)
