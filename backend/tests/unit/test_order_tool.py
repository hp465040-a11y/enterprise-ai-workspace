"""Tool contract tests using mocked Service/Session, without database fixtures."""

import json
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools.order_tool import GetOrderInput, create_get_order_tool
from app.core.exceptions import NotFoundError, ValidationAppError


class GetOrderToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = MagicMock(spec=AsyncSession)
        self.organization_id = uuid4()
        self.tool = create_get_order_tool(self.db, organization_id=self.organization_id)
        self.order = SimpleNamespace(
            order_number="123", platform="shopify", store_key="store-a",
            status="confirmed", payment_status="paid", fulfillment_status="unfulfilled",
            currency="USD", total_amount=Decimal("12.3400"),
            ordered_at=datetime(2026, 9, 30, 10, 0, tzinfo=UTC),
            customer_email="private@example.com", customer_name="Private",
            shipping_address={"private": True}, organization_id=self.organization_id,
        )

    def test_schema_exposes_only_customer_inputs(self):
        schema = self.tool.tool_call_schema.model_json_schema()
        self.assertEqual(set(schema["properties"]), {"order_number", "platform", "store_key"})
        self.assertEqual(schema["required"], ["order_number"])
        self.assertIs(self.tool.get_input_schema().model_json_schema()["additionalProperties"], False)
        self.assertIsNone(schema["properties"]["platform"]["default"])
        self.assertIsNone(schema["properties"]["store_key"]["default"])
        self.assertEqual(self.tool.name, "get_order")

    async def test_trusted_context_cannot_be_overridden(self):
        with patch("app.ai.tools.order_tool.order_service.get_order", new_callable=AsyncMock) as service:
            for field, value in (("organization_id", str(uuid4())), ("db", "attacker-session")):
                with self.subTest(field=field):
                    with self.assertRaises(ValidationError):
                        await self.tool.ainvoke({"order_number": "123", field: value})
            service.assert_not_awaited()

    async def test_found_calls_service_and_serializes_exact_whitelist(self):
        with patch("app.ai.tools.order_tool.order_service.get_order", new_callable=AsyncMock) as service:
            service.return_value = self.order
            result = await self.tool.ainvoke(
                {"order_number": "123", "platform": "shopify", "store_key": "store-a"}
            )
            service.assert_awaited_once_with(
                self.db, organization_id=self.organization_id, order_number="123",
                platform="shopify", store_key="store-a",
            )
        self.assertEqual(result, {
            "status": "found", "error_code": None, "message": None,
            "order": {
                "order_number": "123", "platform": "shopify", "store_key": "store-a",
                "status": "confirmed", "payment_status": "paid",
                "fulfillment_status": "unfulfilled", "currency": "USD",
                "total_amount": "12.3400", "ordered_at": "2026-09-30T10:00:00+00:00",
            },
        })
        json.dumps(result)
        self.db.execute.assert_not_called()

    async def test_omitted_optional_inputs_use_none(self):
        with patch("app.ai.tools.order_tool.order_service.get_order", new_callable=AsyncMock) as service:
            service.return_value = self.order
            await self.tool.ainvoke({"order_number": "123"})
            service.assert_awaited_once_with(
                self.db, organization_id=self.organization_id, order_number="123",
                platform=None, store_key=None,
            )

    async def test_optional_null_spellings_reach_real_service_without_sql_filters(self):
        # Execute the actual Tool and Service; only the session result is a unit-test stub.
        import app.db.base  # noqa: F401 -- register ORM relationships for SQL compilation

        rows = MagicMock()
        rows.scalars.return_value.all.return_value = [self.order]
        self.db.execute = AsyncMock(return_value=rows)
        for value in (None, "null", "None", " NULL ", " none ", "", " \t\n "):
            with self.subTest(value=value):
                result = await self.tool.ainvoke({
                    "order_number": "123", "platform": value, "store_key": value,
                })
                self.assertEqual(result["status"], "found")
                query = self.db.execute.call_args.args[0]
                compiled = query.compile(dialect=postgresql.dialect())
                self.assertEqual(compiled.params, {
                    "organization_id_1": self.organization_id, "order_number_1": "123",
                })
                self.assertNotIn("orders.platform =", str(compiled))
                self.assertNotIn("orders.store_key =", str(compiled))

    def test_null_normalization_is_limited_to_optional_fields_and_exact_tokens(self):
        for value in ("nullable", "none-store", "unknown", "N/A", "  store-a  "):
            with self.subTest(value=value):
                parsed = GetOrderInput(order_number="null", platform=value, store_key=value)
                self.assertEqual(parsed.order_number, "null")
                self.assertEqual(parsed.platform, value)
                self.assertEqual(parsed.store_key, value)
        for value in (123, [], {}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                GetOrderInput(order_number="123", platform=value)

    async def test_expected_domain_results(self):
        cases = (
            (NotFoundError("Order not found"), "not_found", "not_found"),
            (ValidationAppError("Clarify platform/store", error_code="ambiguous_order"),
             "ambiguous", "ambiguous_order"),
            (ValidationAppError("Platform must not be empty"), "invalid_input", "validation_error"),
        )
        for error, status, code in cases:
            with self.subTest(status=status):
                with patch("app.ai.tools.order_tool.order_service.get_order", new_callable=AsyncMock) as service:
                    service.side_effect = error
                    result = await self.tool.ainvoke({"order_number": "123"})
                self.assertEqual(result, {
                    "status": status, "error_code": code, "message": error.message, "order": None,
                })

    async def test_unexpected_errors_propagate(self):
        for error in (ConnectionError("Database unavailable"), RuntimeError("Program error")):
            with self.subTest(error=type(error).__name__):
                with patch("app.ai.tools.order_tool.order_service.get_order", new_callable=AsyncMock) as service:
                    service.side_effect = error
                    with self.assertRaises(type(error)) as caught:
                        await self.tool.ainvoke({"order_number": "123"})
                self.assertIs(caught.exception, error)


if __name__ == "__main__":
    unittest.main()
