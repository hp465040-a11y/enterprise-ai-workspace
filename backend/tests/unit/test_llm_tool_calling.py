"""Provider protocol tests; clients are mocked and no tools are executed."""

import inspect
import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import anthropic
import httpx

from app.ai.llm.anthropic_provider import AnthropicProvider, _to_anthropic_tool_messages
from app.ai.llm.base import LLMMessage, LLMToolCall, LLMToolDefinition, LLMToolMessage
from app.ai.llm.factory import get_llm_provider
from app.ai.llm.ollama_provider import OllamaProvider
from app.ai.tools.order_tool import GetOrderInput
from app.core.config import settings
from app.core.exceptions import UpstreamProviderError


class ToolCallingProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
        with patch("app.ai.llm.anthropic_provider.anthropic.AsyncAnthropic", return_value=self.client):
            self.provider = AnthropicProvider()
        self.definition = LLMToolDefinition(
            name="get_order", description="Look up an order",
            input_schema=GetOrderInput.model_json_schema(),
        )
        self.client.messages.create.return_value = self.response([
            SimpleNamespace(type="text", text="Final answer")
        ])

    @staticmethod
    def response(content, stop_reason="end_turn"):
        return SimpleNamespace(
            content=content, model="mock-model", stop_reason=stop_reason,
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )

    async def test_schema_sent_without_trusted_context(self):
        response = await self.provider.generate_with_tools(
            messages=[LLMToolMessage(role="user", content="查 A100")],
            tools=[self.definition], system="Customer support", max_tokens=100,
        )
        request = self.client.messages.create.call_args.kwargs
        self.assertEqual(request["tools"], [{
            "name": "get_order", "description": "Look up an order",
            "input_schema": self.definition.input_schema,
        }])
        schema = request["tools"][0]["input_schema"]
        self.assertEqual(set(schema["properties"]), {"order_number", "platform", "store_key"})
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(request["thinking"], {"type": "disabled"})
        self.assertEqual(request["tool_choice"], {"type": "auto", "disable_parallel_tool_use": True})
        self.assertEqual(request["max_tokens"], 100)
        self.assertEqual(response.usage.input_tokens, 10)
        self.assertEqual(response.content, "Final answer")
        self.assertEqual(response.tool_calls, [])

    async def test_text_and_tool_use_parse_and_result_roundtrip(self):
        self.client.messages.create.return_value = self.response([
            SimpleNamespace(type="text", text="Checking order."),
            SimpleNamespace(type="tool_use", id="toolu_1", name="get_order",
                            input={"order_number": "A100", "platform": "amazon"}),
        ], stop_reason="tool_use")
        user = LLMToolMessage(role="user", content="查 Amazon 的 A100")
        response = await self.provider.generate_with_tools(messages=[user], tools=[self.definition])
        expected_call = LLMToolCall(
            id="toolu_1", name="get_order", arguments={"order_number": "A100", "platform": "amazon"}
        )
        self.assertEqual(response.tool_calls, [expected_call])
        self.assertEqual(response.content, "Checking order.")
        self.assertEqual(response.stop_reason, "tool_use")
        self.client.messages.create.return_value = self.response([
            SimpleNamespace(type="text", text="Order found.")
        ])
        await self.provider.generate_with_tools(messages=[
            user,
            LLMToolMessage(role="assistant", content=response.content, tool_calls=response.tool_calls),
            LLMToolMessage(role="tool", content='{"status":"found"}',
                           tool_call_id="toolu_1", tool_name="get_order"),
        ], tools=[self.definition])
        sent = self.client.messages.create.call_args.kwargs["messages"]
        self.assertEqual(sent, [
            {"role": "user", "content": "查 Amazon 的 A100"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Checking order."},
                {"type": "tool_use", "id": "toolu_1", "name": "get_order",
                 "input": {"order_number": "A100", "platform": "amazon"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"status":"found"}'},
            ]},
        ])

    def test_multiple_results_are_grouped_and_preserve_ids(self):
        messages = [
            LLMToolMessage(role="assistant", tool_calls=[
                LLMToolCall(id="a", name="get_order", arguments={"order_number": "1"}),
                LLMToolCall(id="b", name="get_order", arguments={"order_number": "2"}),
            ]),
            LLMToolMessage(role="tool", tool_call_id="a", content="first"),
            LLMToolMessage(role="tool", tool_call_id="b", content="second"),
            LLMToolMessage(role="assistant", content="Done"),
        ]
        sent = _to_anthropic_tool_messages(messages)
        self.assertEqual(len(sent), 3)
        self.assertEqual(sent[1], {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "a", "content": "first"},
            {"type": "tool_result", "tool_use_id": "b", "content": "second"},
        ]})

    async def test_invalid_tool_message_fails_before_sdk_request(self):
        for message in (
            LLMToolMessage(role="tool", content="Missing ID"),
            LLMToolMessage(role="user", tool_calls=[LLMToolCall(id="a", name="get_order", arguments={})]),
        ):
            with self.subTest(role=message.role):
                with self.assertRaises(ValueError):
                    await self.provider.generate_with_tools(messages=[message], tools=[self.definition])
        self.client.messages.create.assert_not_awaited()

    async def test_no_tools_omits_tools_and_choice(self):
        await self.provider.generate_with_tools(
            messages=[LLMToolMessage(role="user", content="hello")], tools=[]
        )
        request = self.client.messages.create.call_args.kwargs
        self.assertIs(request["tools"], anthropic.omit)
        self.assertIs(request["tool_choice"], anthropic.omit)

    async def test_ollama_tool_calling_is_implemented(self):
        provider = OllamaProvider.__new__(OllamaProvider)
        provider._model = "llama3.1:8b"
        provider._client = SimpleNamespace(post=AsyncMock(return_value=httpx.Response(
            200, json={"message": {"content": "Hello"}, "done_reason": "stop"},
            request=httpx.Request("POST", "http://ollama/api/chat"),
        )))
        response = await provider.generate_with_tools(
            messages=[LLMToolMessage(role="user", content="hello")], tools=[],
        )
        self.assertEqual(response.content, "Hello")
        self.assertEqual(response.tool_calls, [])

    async def test_provider_api_error_mapping(self):
        self.client.messages.create.side_effect = anthropic.APIConnectionError(request=None)
        with self.assertRaises(UpstreamProviderError):
            await self.provider.generate_with_tools(messages=[], tools=[self.definition])

    async def test_original_generate_uses_original_protocol(self):
        response = await self.provider.generate(
            messages=[LLMMessage(role="user", content="hello")], enable_thinking=False
        )
        request = self.client.messages.create.call_args.kwargs
        self.assertEqual(request["messages"], [{"role": "user", "content": "hello"}])
        self.assertNotIn("tools", request)
        self.assertNotIn("tool_choice", request)
        self.assertEqual(response.content, "Final answer")

    async def test_original_stream_uses_original_protocol(self):
        async def chunks():
            yield "Final "
            yield "answer"

        raw = SimpleNamespace(
            text_stream=chunks(),
            get_final_message=AsyncMock(return_value=self.response([
                SimpleNamespace(type="text", text="Final answer")
            ])),
        )
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=raw)
        context.__aexit__ = AsyncMock(return_value=False)
        self.client.messages.stream = MagicMock(return_value=context)
        async with self.provider.stream(messages=[LLMMessage(role="user", content="hello")]) as stream:
            self.assertEqual("".join([part async for part in stream.text_stream]), "Final answer")
            self.assertEqual((await stream.get_final_response()).content, "Final answer")
        request = self.client.messages.stream.call_args.kwargs
        self.assertEqual(request["messages"], [{"role": "user", "content": "hello"}])
        self.assertNotIn("tools", request)
        self.assertNotIn("tool_choice", request)

    async def test_existing_provider_unit_tests_without_pytest_fixtures(self):
        # Execute existing deterministic tests directly, avoiding the root
        # pytest conftest that imports the app and provides DB create/drop fixtures.
        from tests.unit import test_ai_providers as legacy

        try:
            with patch.object(settings, "LLM_PROVIDER", "anthropic"), patch(
                "app.ai.llm.anthropic_provider.anthropic.AsyncAnthropic", return_value=self.client
            ):
                get_llm_provider.cache_clear()
                for name, function in inspect.getmembers(legacy, inspect.isfunction):
                    if not name.startswith("test_"):
                        continue
                    with self.subTest(name=name), ExitStack() as stack:
                        monkeypatch = SimpleNamespace(
                            setattr=lambda target, key, value: stack.enter_context(patch.object(target, key, value))
                        )
                        result = function(monkeypatch) if "monkeypatch" in inspect.signature(function).parameters else function()
                        if inspect.isawaitable(result):
                            await result
        finally:
            get_llm_provider.cache_clear()


class OllamaToolCallingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = OllamaProvider.__new__(OllamaProvider)
        self.provider._model = "llama3.1:8b"
        self.client = SimpleNamespace(post=AsyncMock())
        self.provider._client = self.client
        self.definition = LLMToolDefinition("get_order", "Look up order", GetOrderInput.model_json_schema())
        self.user = LLMToolMessage(role="user", content="Query DAY3-TEST-001")
        self.respond({"content": "Done"})

    def respond(self, message, **extra):
        self.client.post.return_value = httpx.Response(
            200, json={"message": message, "done_reason": "stop", **extra},
            request=httpx.Request("POST", "http://ollama/api/chat"),
        )

    async def call(self, messages=None, tools=None, **kwargs):
        return await self.provider.generate_with_tools(
            messages=[self.user] if messages is None else messages,
            tools=[self.definition] if tools is None else tools, **kwargs,
        )

    async def test_schema_system_options_and_final_text(self):
        self.respond({"content": "Done"}, prompt_eval_count=10, eval_count=5)
        response = await self.call(system="Support", max_tokens=100)
        payload = self.client.post.call_args.kwargs["json"]
        self.assertEqual(self.client.post.call_args.args, ("/api/chat",))
        self.assertEqual(payload["tools"], [{"type": "function", "function": {
            "name": "get_order", "description": "Look up order",
            "parameters": self.definition.input_schema,
        }}])
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "Support"})
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["options"], {"num_predict": 100, "temperature": 0})
        self.assertEqual(response.content, "Done")
        self.assertEqual(response.usage.input_tokens, 10)
        self.assertEqual(response.usage.output_tokens, 5)

    async def test_call_and_result_roundtrip_without_native_ids(self):
        arguments = {"order_number": "DAY3-TEST-001", "platform": "amazon"}
        self.respond({"content": "Checking", "tool_calls": [{"function": {
            "name": "get_order", "arguments": arguments,
        }}]})
        first = await self.call()
        second = await self.call()
        call = first.tool_calls[0]
        self.assertTrue(call.id)
        self.assertNotEqual(call.id, second.tool_calls[0].id)
        self.assertEqual(call.arguments, arguments)
        self.assertEqual(first.stop_reason, "tool_use")
        result = '{"status":"found"}'
        self.respond({"content": "Order found"})
        final = await self.call(messages=[self.user,
            LLMToolMessage(role="assistant", content=first.content, tool_calls=first.tool_calls),
            LLMToolMessage(role="tool", tool_call_id=call.id, content=result),
        ])
        sent = self.client.post.call_args.kwargs["json"]["messages"]
        self.assertEqual(sent[1], {"role": "assistant", "content": "Checking", "tool_calls": [
            {"type": "function", "function": {"name": "get_order", "arguments": arguments}},
        ]})
        self.assertEqual(sent[2], {"role": "tool", "tool_name": "get_order", "content": result})
        self.assertEqual(final.content, "Order found")

    async def test_json_string_arguments_and_invalid_arguments(self):
        for arguments in ({"order_number": "A100"}, '{"order_number":"A100"}'):
            self.respond({"tool_calls": [{"function": {"name": "get_order", "arguments": arguments}}]})
            self.assertEqual((await self.call()).tool_calls[0].arguments, {"order_number": "A100"})
        for arguments in ([], "[]", "invalid json"):
            self.respond({"tool_calls": [{"function": {"name": "get_order", "arguments": arguments}}]})
            with self.assertRaises(ValueError):
                await self.call()

    async def test_invalid_correlation_fails_before_http(self):
        call = LLMToolCall("a", "get_order", {"order_number": "A100"})
        assistant = LLMToolMessage(role="assistant", tool_calls=[call])
        for messages in (
            [LLMToolMessage(role="tool", tool_call_id="a")],
            [assistant],
            [assistant, LLMToolMessage(role="tool", tool_call_id="wrong")],
            [assistant, LLMToolMessage(role="tool", tool_call_id="a", tool_name="wrong")],
            [LLMToolMessage(role="user", tool_calls=[call])],
        ):
            with self.subTest(messages=messages), self.assertRaises(ValueError):
                await self.call(messages=messages)
        self.client.post.assert_not_awaited()

    async def test_multiple_same_name_calls_correlate_by_order(self):
        calls = [LLMToolCall("a", "get_order", {}), LLMToolCall("b", "get_order", {})]
        assistant = LLMToolMessage(role="assistant", tool_calls=calls)
        with self.assertRaises(ValueError):
            await self.call(messages=[assistant, LLMToolMessage(role="tool", tool_call_id="b")])
        await self.call(messages=[assistant,
            LLMToolMessage(role="tool", tool_call_id="a", content="first"),
            LLMToolMessage(role="tool", tool_call_id="b", content="second"),
        ])
        sent = self.client.post.call_args.kwargs["json"]["messages"]
        self.assertEqual([m["content"] for m in sent[1:]], ["first", "second"])

    async def test_no_tools_and_truncation_mapping(self):
        self.respond({"content": "partial"}, done_reason="length")
        response = await self.call(tools=[])
        self.assertNotIn("tools", self.client.post.call_args.kwargs["json"])
        self.assertEqual(response.stop_reason, "max_tokens")

    async def test_http_errors_map_to_provider_error(self):
        self.client.post.side_effect = httpx.ConnectError("offline")
        with self.assertRaises(UpstreamProviderError):
            await self.call()
        self.client.post.side_effect = None
        self.client.post.return_value = httpx.Response(
            500, request=httpx.Request("POST", "http://ollama/api/chat"),
        )
        with self.assertRaises(UpstreamProviderError):
            await self.call()

    async def test_customer_agent_roundtrip_with_ollama_adapter(self):
        from datetime import datetime, timezone
        from decimal import Decimal
        from sqlalchemy.ext.asyncio import AsyncSession
        from app.ai.agents.customer_agent import run_customer_agent

        order = SimpleNamespace(
            order_number="DAY3-TEST-001", platform="amazon", store_key="day3-test-store",
            status="confirmed", payment_status="paid", fulfillment_status="unfulfilled",
            currency="USD", total_amount=Decimal("12.00"), ordered_at=datetime.now(timezone.utc),
        )
        self.respond({"content": "", "tool_calls": [{"function": {
            "name": "get_order", "arguments": {
                "order_number": "DAY3-TEST-001", "platform": "null", "store_key": "None",
            },
        }}]})
        first = self.client.post.return_value
        self.respond({"content": "Order confirmed, USD 12.00"})
        self.client.post.side_effect = [first, self.client.post.return_value]
        db = MagicMock(spec=AsyncSession)
        organization_id = uuid4()
        with patch("app.ai.tools.order_tool.order_service.get_order", new_callable=AsyncMock,
                   return_value=order) as service:
            answer = await run_customer_agent(
                self.provider, db, organization_id=organization_id, user_message=self.user.content,
            )
        self.assertEqual(answer, "Order confirmed, USD 12.00")
        service.assert_awaited_once_with(db, organization_id=organization_id,
            order_number="DAY3-TEST-001", platform=None, store_key=None)
        sent = self.client.post.call_args.kwargs["json"]["messages"]
        result = json.loads(sent[-1]["content"])
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["order"]["total_amount"], "12.00")

    async def test_original_generate_and_stream_keep_plain_protocol(self):
        self.assertEqual((await self.provider.generate(messages=[LLMMessage("user", "hello")])).content, "Done")
        self.assertNotIn("tools", self.client.post.call_args.kwargs["json"])
        response = httpx.Response(200, content=(json.dumps({
            "message": {"content": "Streamed"}, "done": True,
        }) + "\n").encode(), request=httpx.Request("POST", "http://ollama/api/chat"))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        self.client.stream = MagicMock(return_value=context)
        async with self.provider.stream(messages=[LLMMessage("user", "hello")]) as stream:
            self.assertEqual("".join([chunk async for chunk in stream.text_stream]), "Streamed")
        self.assertNotIn("tools", self.client.stream.call_args.kwargs["json"])


if __name__ == "__main__":
    unittest.main()
