"""Fake/mock loop tests, without network requests or database fixtures."""

import copy
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.customer_agent import (
    CustomerAgentLimitError,
    CustomerAgentProtocolError,
    run_customer_agent,
)
from app.ai.llm.base import LLMToolCall, LLMToolMessage, LLMToolResponse
from app.ai.tools.order_tool import create_get_order_tool


class FakeProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def generate_with_tools(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return next(self.responses)


def text_response(text):
    return LLMToolResponse(content=text, model="fake", stop_reason="end_turn")


def call_response(call_id="call-1", name="get_order", arguments=None):
    return LLMToolResponse(
        content="", model="fake", stop_reason="tool_use",
        tool_calls=[LLMToolCall(id=call_id, name=name, arguments=arguments or {"order_number": "A100"})],
    )


class CustomerAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = MagicMock(spec=AsyncSession)
        self.organization_id = uuid4()
        real_tool = create_get_order_tool(self.db, organization_id=self.organization_id)
        self.tool = MagicMock()
        self.tool.name = real_tool.name
        self.tool.description = real_tool.description
        self.tool.get_input_schema.return_value = real_tool.get_input_schema()
        self.tool.ainvoke = AsyncMock(return_value={
            "status": "found", "error_code": None, "message": None,
            "order": {"order_number": "A100", "platform": "亚马逊"},
        })

    async def run_agent(self, provider, **kwargs):
        with patch("app.ai.agents.customer_agent.create_get_order_tool", return_value=self.tool) as factory:
            result = await run_customer_agent(
                provider, self.db, organization_id=self.organization_id, user_message="查 A100", **kwargs,
            )
            factory.assert_called_once_with(self.db, organization_id=self.organization_id)
            return result

    async def test_direct_answer_does_not_execute_tool(self):
        provider = FakeProvider([text_response("您好")])
        self.assertEqual(await self.run_agent(provider), "您好")
        self.tool.ainvoke.assert_not_awaited()
        self.assertEqual(len(provider.requests), 1)
        definition = provider.requests[0]["tools"][0]
        self.assertEqual(definition.name, self.tool.name)
        self.assertEqual(definition.description, self.tool.description)
        self.assertEqual(definition.input_schema, self.tool.get_input_schema().model_json_schema())
        self.assertEqual(set(definition.input_schema["properties"]), {"order_number", "platform", "store_key"})

    async def test_found_roundtrip_json_and_call_id(self):
        provider = FakeProvider([call_response(), text_response("已找到 A100")])
        self.assertEqual(await self.run_agent(provider), "已找到 A100")
        self.tool.ainvoke.assert_awaited_once_with({"order_number": "A100"})
        messages = provider.requests[1]["messages"]
        self.assertEqual(messages[-2].role, "assistant")
        self.assertEqual(messages[-2].tool_calls[0].id, "call-1")
        result_message = messages[-1]
        self.assertEqual(result_message.role, "tool")
        self.assertEqual(result_message.tool_call_id, "call-1")
        self.assertEqual(result_message.tool_name, "get_order")
        self.assertEqual(json.loads(result_message.content), self.tool.ainvoke.return_value)
        self.assertIn("亚马逊", result_message.content)
        self.assertNotIn("organization_id", result_message.content)
        self.assertNotIn('"db"', result_message.content)

    async def test_terminal_business_results_disable_tools(self):
        for status, answer in (
            ("ambiguous", "请问是哪个平台或店铺？"),
            ("not_found", "未找到该订单"),
            ("invalid_input", "请补充有效订单号"),
        ):
            with self.subTest(status=status):
                self.tool.ainvoke.reset_mock()
                self.tool.ainvoke.return_value = {"status": status, "order": None}
                provider = FakeProvider([call_response(), text_response(answer)])
                self.assertEqual(await self.run_agent(provider), answer)
                self.assertEqual(provider.requests[1]["tools"], [])
                self.assertEqual(json.loads(provider.requests[1]["messages"][-1].content)["status"], status)
                self.tool.ainvoke.assert_awaited_once_with({"order_number": "A100"})

    async def test_unregistered_tool_fails_without_execution(self):
        provider = FakeProvider([call_response(name="create_return_request")])
        with self.assertRaisesRegex(CustomerAgentProtocolError, "Unregistered tool"):
            await self.run_agent(provider)
        self.tool.ainvoke.assert_not_awaited()
        self.assertEqual(len(provider.requests), 1)

    async def test_system_exception_stops_without_second_model_request(self):
        error = ConnectionError("Private database error")
        self.tool.ainvoke.side_effect = error
        provider = FakeProvider([call_response()])
        with self.assertRaises(ConnectionError) as caught:
            await self.run_agent(provider)
        self.assertIs(caught.exception, error)
        self.assertEqual(len(provider.requests), 1)

    async def test_tool_call_budget(self):
        provider = FakeProvider([call_response("a"), call_response("b"), call_response("c")])
        with self.assertRaisesRegex(CustomerAgentLimitError, "tool call count"):
            await self.run_agent(provider)
        self.assertEqual(self.tool.ainvoke.await_count, 2)
        self.assertEqual(len(provider.requests), 3)

    async def test_model_request_budget(self):
        provider = FakeProvider([call_response()])
        # Lower the fixed budget to exercise its independent boundary, without
        # permitting any additional request or a tool whose result cannot be consumed.
        with patch("app.ai.agents.customer_agent.MAX_MODEL_REQUESTS", 1):
            with self.assertRaisesRegex(CustomerAgentLimitError, "model request count"):
                await self.run_agent(provider)
        self.assertEqual(len(provider.requests), 1)
        self.tool.ainvoke.assert_not_awaited()

    async def test_two_calls_then_final_answer_fit_budgets(self):
        provider = FakeProvider([call_response("a"), call_response("b"), text_response("Done")])
        self.assertEqual(await self.run_agent(provider), "Done")
        self.assertEqual(len(provider.requests), 3)
        self.assertEqual(self.tool.ainvoke.await_count, 2)

    async def test_empty_final_answer_is_failure(self):
        with self.assertRaisesRegex(CustomerAgentProtocolError, "empty final answer"):
            await self.run_agent(FakeProvider([text_response("  ")]))

    async def test_tool_call_after_terminal_result_is_rejected(self):
        self.tool.ainvoke.return_value = {"status": "ambiguous", "order": None}
        provider = FakeProvider([call_response(), call_response("b")])
        with self.assertRaisesRegex(CustomerAgentProtocolError, "final-answer-only"):
            await self.run_agent(provider)
        self.assertEqual(self.tool.ainvoke.await_count, 1)

    async def test_duplicate_call_id_is_rejected(self):
        provider = FakeProvider([call_response("a"), call_response("a")])
        with self.assertRaisesRegex(CustomerAgentProtocolError, "duplicate"):
            await self.run_agent(provider)
        self.assertEqual(self.tool.ainvoke.await_count, 1)

    async def test_multiple_calls_in_one_response_execute_none(self):
        response = call_response("a")
        response.tool_calls.append(LLMToolCall(id="b", name="get_order", arguments={"order_number": "B200"}))
        with self.assertRaisesRegex(CustomerAgentProtocolError, "one tool call"):
            await self.run_agent(FakeProvider([response]))
        self.tool.ainvoke.assert_not_awaited()

    async def test_execution_validation_error_is_not_treated_as_input_error(self):
        try:
            self.tool.get_input_schema().model_validate({})
        except ValidationError as error:
            self.tool.ainvoke.side_effect = error
            provider = FakeProvider([call_response()])
            with self.assertRaises(ValidationError) as caught:
                await self.run_agent(provider)
            self.assertIs(caught.exception, error)
            self.assertEqual(len(provider.requests), 1)
        else:
            self.fail("Expected an input validation error for the test setup")

    async def test_history_is_used_without_mutating_caller_list(self):
        history = [LLMToolMessage(role="user", content="订单是 A100")]
        provider = FakeProvider([text_response("Done")])
        await self.run_agent(provider, history=history)
        self.assertEqual(len(history), 1)
        self.assertEqual(provider.requests[0]["messages"][0], history[0])

    async def test_real_tool_schema_blocks_context_override_without_service_call(self):
        # Use the real StructuredTool validator but mock the Service completely.
        for field in ("organization_id", "db"):
            with self.subTest(field=field), patch(
                "app.ai.tools.order_tool.order_service.get_order", new_callable=AsyncMock
            ) as service:
                real_tool = create_get_order_tool(self.db, organization_id=self.organization_id)
                provider = FakeProvider([
                    call_response(arguments={"order_number": "A100", field: "attacker"}),
                    text_response("请提供有效参数"),
                ])
                with patch("app.ai.agents.customer_agent.create_get_order_tool", return_value=real_tool) as factory:
                    await run_customer_agent(
                        provider, self.db, organization_id=self.organization_id, user_message="查 A100",
                    )
                factory.assert_called_once_with(self.db, organization_id=self.organization_id)
                service.assert_not_awaited()
                self.assertEqual(provider.requests[1]["tools"], [])
                self.assertEqual(json.loads(provider.requests[1]["messages"][-1].content)["status"], "invalid_input")


if __name__ == "__main__":
    unittest.main()
