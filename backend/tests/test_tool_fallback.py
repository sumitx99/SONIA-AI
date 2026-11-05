"""Fallback keeps MCP/web actions in the same policy and progress loop."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

import requests
from app.mcp_client import agent
from app.mcp_client import store
from app.services import llm
from app.api import chat
from test_llm import response
from test_mcp_client import registry, CALL, ANSWER


class ToolFallbackTests(unittest.TestCase):
    def test_api_does_not_drop_connected_tools_for_a_plain_fallback(self):
        async def failed(*args, **kwargs):
            raise requests.Timeout("tool generation unavailable")
            yield  # async generator, not a coroutine
        async def run():
            return [event async for event in chat._answer_events("user1", "read", "", [{"name": "read"}], {}, [])]
        with patch.object(chat, "answer_with_tools", failed), patch.object(chat, "backup_configured", return_value=True), \
             patch.object(chat, "stream_backup_answer") as plain:
            with self.assertRaises(requests.Timeout):
                asyncio.run(run())
        plain.assert_not_called()

    def test_unreadable_secret_is_scoped_to_its_connection(self):
        row = {"id": "conn-1", "name": "Notes", "url": "https://notes.example.com/mcp",
               "auth_type": "header", "enabled": True, "last_error": None, "created_at": Mock(),
               "tools": [{"name": "read", "read_only": True}], "tool_policies": {}, "secret": b"old-key"}
        with patch.object(store, "decrypt_secret", side_effect=store.SecretKeyMissing("private diagnostic")):
            connection = store._row(row, with_secret=True)
        self.assertIsNone(connection["secret"])
        self.assertIn("Reconnect", connection["unavailable_reason"])
        self.assertNotIn("private diagnostic", str(connection))
        with patch.object(agent, "open_session") as open_session:
            text, is_error = asyncio.run(agent._run_tool("user1", connection, {"name": "read"}, {}))
        self.assertTrue(is_error)
        self.assertIn("Reconnect", text)
        open_session.assert_not_called()
        with patch.object(store, "decrypt_secret") as decrypt:
            healthy = store._row({**row, "auth_type": "none"}, with_secret=True)
        self.assertNotIn("unavailable_reason", healthy)
        decrypt.assert_not_called()

    def test_mcp_fallback_still_emits_running_and_done_and_preserves_result(self):
        declarations, tools = registry("allow")
        seen = []
        def backup(contents, offered, **kwargs):
            seen.append((list(contents), offered))
            return iter(CALL if len(seen) == 1 else ANSWER)
        async def run():
            return [event async for event in agent.answer_with_tools("user1", "read my notes", "ctx", declarations, tools)]
        with patch.object(agent, "stream_gemini_parts", side_effect=requests.HTTPError(response=Mock(status_code=429))), \
             patch.object(agent, "backup_configured", return_value=True), \
             patch.object(agent, "stream_tool_backup", backup), \
             patch.object(agent, "_run_tool", AsyncMock(return_value=("Saved note", False))) as execute:
            events = asyncio.run(run())
        cards = [data for kind, data in events if kind == "tool_call"]
        self.assertEqual([card["status"] for card in cards], ["running", "done"])
        self.assertEqual(cards[0]["id"], cards[1]["id"])
        self.assertEqual(cards[0]["server"], "Notes")
        self.assertIn("c0__create_note", [item["name"] for item in seen[0][1]])
        execute.assert_awaited_once()
        self.assertIn("Saved note", str(seen[1][0]))

    def test_first_round_catalog_rejection_preserves_connected_tools_on_backup(self):
        declarations, tools = registry("allow")

        async def run():
            return [event async for event in agent.answer_with_tools("user1", "read", "", declarations, tools)]

        error = requests.HTTPError(response=Mock(status_code=400))
        with patch.object(agent, "stream_gemini_parts", side_effect=error), \
             patch.object(agent, "backup_configured", return_value=True), \
             patch.object(agent, "stream_tool_backup", return_value=iter(ANSWER)) as backup:
            self.assertEqual(asyncio.run(run()), [("delta", {"text": "Done."})])
        self.assertIn(declarations[0], backup.call_args.args[1])

    def test_fallback_cannot_bypass_mcp_approval(self):
        declarations, tools = registry("ask")
        rounds = iter([CALL, ANSWER])
        async def run():
            events = []
            async for kind, data in agent.answer_with_tools("user1", "make a note", "ctx", declarations, tools):
                events.append((kind, data))
                if kind == "approval_required":
                    agent.resolve_approval("user1", data["id"], False)
            return events
        with patch.object(agent, "stream_gemini_parts", side_effect=requests.HTTPError(response=Mock(status_code=503))), \
             patch.object(agent, "backup_configured", return_value=True), \
             patch.object(agent, "stream_tool_backup", side_effect=lambda *a, **kw: iter(next(rounds))), \
             patch.object(agent, "_run_tool", AsyncMock()) as execute:
            events = asyncio.run(run())
        self.assertEqual([data["status"] for kind, data in events if kind == "tool_call"], ["awaiting_approval", "denied"])
        execute.assert_not_awaited()

    def test_fragmented_tool_arguments_and_private_reasoning(self):
        fragments = [{"reasoning": "private"}, {"tool_calls": [{"index": 0, "id": "call1", "function": {
            "name": "c0__read_note", "arguments": '{"name":'}}]},
            {"tool_calls": [{"index": 0, "function": {"arguments": '"plan"}'}}]}]
        reply = response(200, [{"choices": [{"delta": delta}]} for delta in fragments])
        with patch.object(llm, "GROQ_MODELS", ["test"]), patch.object(llm.requests, "post", return_value=reply) as post:
            parts = list(llm.stream_tool_backup(llm.conversation_turns("read", "ctx"),
                [{"name": "c0__read_note", "parametersJsonSchema": {"type": "object"}}], allow_web=False))
        self.assertEqual(parts, [{"functionCall": {"id": "call1", "name": "c0__read_note", "args": {"name": "plan"}}}])
        self.assertEqual(post.call_args.kwargs["json"]["tool_choice"], "auto")
        self.assertNotIn("private", str(parts))

    def test_last_round_has_no_tools_even_when_web_is_available(self):
        with patch.object(llm, "GROQ_MODELS", ["test"]), patch.object(llm, "web_search_available", return_value=True), \
             patch.object(llm.requests, "post", return_value=response(200)) as post:
            list(llm.stream_tool_backup([], [], allow_web=False))
        self.assertNotIn("tools", post.call_args.kwargs["json"])

    def test_a_selected_web_tool_has_separate_web_progress(self):
        calls = iter([[{"functionCall": {"id": "search1", "name": "web_search", "args": {"query": "official pricing"}}}], ANSWER])
        async def run():
            return [event async for event in agent.answer_with_tools("user1", "latest pricing", "", [], {})]
        with patch.object(agent, "stream_gemini_parts", side_effect=lambda *args: iter(next(calls))), \
             patch.object(agent, "search_web", return_value=("Prices", [{"title": "Official", "url": "https://example.com"}], [])):
            events = asyncio.run(run())
        cards = [data for kind, data in events if kind == "tool_call"]
        self.assertEqual([card["status"] for card in cards], ["running", "done"])
        self.assertTrue(all(card["server"] == "Web" for card in cards))
        self.assertEqual(cards[0]["id"], cards[1]["id"])

    def test_failed_web_request_is_never_reported_as_complete(self):
        calls = iter([[{"functionCall": {"id": "search1", "name": "web_search", "args": {"query": "pricing"}}}], ANSWER])
        async def run():
            return [event async for event in agent.answer_with_tools("user1", "latest pricing", "", [], {})]
        with patch.object(agent, "stream_gemini_parts", side_effect=lambda *args: iter(next(calls))), \
             patch.object(agent, "search_web", side_effect=RuntimeError("timeout")):
            events = asyncio.run(run())
        cards = [data for kind, data in events if kind == "tool_call"]
        self.assertEqual([card["status"] for card in cards], ["running", "error"])
        self.assertFalse(any(kind == "sources" for kind, _ in events))

    def test_tool_results_stay_paired_with_call_ids_on_fallback(self):
        contents = [{"role": "user", "parts": [{"text": "Read plan"}]},
                    {"role": "model", "parts": [{"functionCall": {"id": "m1", "name": "read", "args": {"name": "plan"}}}]},
                    {"role": "user", "parts": [{"functionResponse": {"id": "m1", "name": "read", "response": {"result": "Tuesday"}}}]}]
        with patch.object(llm, "GROQ_MODELS", ["test"]), patch.object(llm.requests, "post", return_value=response(200)) as post:
            list(llm.stream_tool_backup(contents, [], allow_web=False))
        messages = post.call_args.kwargs["json"]["messages"]
        self.assertEqual(messages[-2]["tool_calls"][0]["id"], messages[-1]["tool_call_id"])
        self.assertEqual(json.loads(messages[-1]["content"]), {"result": "Tuesday"})


class BackupRequestSizeTests(unittest.TestCase):
    def test_oversized_context_is_shortened_without_dropping_connected_tools(self):
        messages = [{"role": "system", "content": "S" * 8000}, {"role": "user", "content": "C" * 40000}]
        tools = [{"type": "function", "function": {"name": name, "description": "d" * 3000, "parameters": {}}}
                 for name in ("c0__zapier", "web_search")]
        fitted, kept = llm._fit_groq_request(messages, tools)
        self.assertEqual([tool["function"]["name"] for tool in kept], ["c0__zapier", "web_search"])
        self.assertEqual(fitted[0]["content"], "S" * 8000)
        self.assertLessEqual(llm._estimated_tokens([fitted, kept]), llm.GROQ_REQUEST_TOKENS)
        self.assertTrue(fitted[1]["content"].startswith("…[shortened to fit the backup model]"))

    def test_large_catalog_reuses_the_selected_tool_with_its_full_schema(self):
        schema = {"type": "object", "properties": {"profile_url": {"type": "string"}}, "required": ["profile_url"]}
        declarations = [{"name": f"c0__tool_{index}", "description": "d" * 1024,
                         "parametersJsonSchema": schema} for index in range(40)]
        selected = declarations[-1]["name"]
        choose = {"functionCall": {"name": "select_tools", "args": {"names": ["invented", selected]}}}
        execute = {"functionCall": {"id": "profile", "name": selected,
                                    "args": {"profile_url": "https://example.com/profile"}}}
        contents = llm.conversation_turns("Use the connected service to read a profile", "")
        with patch.object(llm, "_stream_groq_parts",
                          side_effect=[iter([choose]), iter([execute]), iter(ANSWER), iter(ANSWER)]) as stream:
            self.assertEqual(list(llm.stream_tool_backup(contents, declarations, allow_web=False)), [execute])
            contents.extend([{"role": "model", "parts": [execute]}, {"role": "user", "parts": [{
                "functionResponse": {"id": "profile", "name": selected, "response": {"headline": "Engineer"}}}]}])
            self.assertEqual(list(llm.stream_tool_backup(contents, declarations, allow_web=False)), ANSWER)
            self.assertEqual(list(llm.stream_tool_backup(contents, [], allow_web=False)), ANSWER)
        selection, execution, follow_up, final = stream.call_args_list
        self.assertEqual(selection.kwargs["tool_choice"], "required")
        self.assertIn(selected, selection.args[0][1]["content"])
        self.assertEqual([tool["function"] for tool in execution.args[1]], [{
            "name": selected, "description": "d" * 1024, "parameters": schema}])
        self.assertEqual(follow_up.args[1], execution.args[1])
        self.assertEqual(json.loads(follow_up.args[0][-1]["content"]), {"headline": "Engineer"})
        self.assertEqual(final.args[1], [])

    def test_small_requests_are_sent_unchanged(self):
        messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "question"}]
        tools = [{"type": "function", "function": {"name": "c0__notes", "description": "", "parameters": {}}}]
        self.assertEqual(llm._fit_groq_request(list(messages), list(tools)), (messages, tools))

    def test_a_request_too_large_for_one_model_tries_the_next(self):
        too_large, ok = response(413), response(200, [])
        ok.iter_lines.return_value = ['data: {"choices": [{"delta": {"content": "Answer"}}]}', "data: [DONE]"]
        with patch.object(llm, "GROQ_API_KEY", "k"), patch.object(llm, "GROQ_MODELS", ["big", "small"]), \
             patch.object(llm.requests, "post", side_effect=[too_large, ok]) as post:
            parts = list(llm.stream_tool_backup([{"role": "user", "parts": [{"text": "hi"}]}], [], allow_web=False))
        self.assertEqual(parts, [{"text": "Answer"}])
        self.assertEqual([call.kwargs["json"]["model"] for call in post.call_args_list], ["big", "small"])
