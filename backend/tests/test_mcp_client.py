"""Sonia as an MCP client: URL safety, secret storage, the tool loop and approvals."""

import asyncio
import json
import importlib
import os
import socket
import sys
import types
import unittest
from base64 import b64encode
from unittest.mock import AsyncMock, Mock, patch

import requests
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

parser = types.ModuleType("app.services.parsing.docling_utils")
parser.process_pdf_with_docling = Mock()
parser.docling_enabled = Mock(return_value=False)
sys.modules.setdefault("app.services.parsing.docling_utils", parser)
backend = importlib.import_module("app.main")
from app.core.auth import current_user  # noqa: E402
agent = importlib.import_module("app.mcp_client.agent")
connections = importlib.import_module("app.mcp_client.connections")
safety = importlib.import_module("app.mcp_client.safety")
store = importlib.import_module("app.mcp_client.store")
oauth = importlib.import_module("app.mcp_client.oauth")
session_module = importlib.import_module("app.mcp_client.session")


def resolving_to(*addresses):
    loop = Mock()
    loop.getaddrinfo = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 443))
                                               for a in addresses])
    return patch.object(safety.asyncio, "get_running_loop", return_value=loop)


class URLSafetyTests(unittest.TestCase):
    def check(self, url):
        return asyncio.run(safety.assert_public_url(url))

    def test_public_https_is_allowed(self):
        with resolving_to("93.184.216.34"), patch.dict(os.environ, {"MCP_ALLOW_PRIVATE_URLS": "false"}):
            self.assertEqual(self.check(" https://mcp.example.com/mcp "), "https://mcp.example.com/mcp")

    def test_private_local_and_metadata_addresses_are_refused(self):
        with patch.dict(os.environ, {"MCP_ALLOW_PRIVATE_URLS": "false"}):
            for address in ("127.0.0.1", "10.1.2.3", "192.168.1.5", "169.254.169.254", "100.64.0.1",
                            "::1", "::ffff:127.0.0.1", "fd00::1"):
                with resolving_to(address), self.assertRaises(safety.UnsafeURLError, msg=address):
                    self.check("https://sneaky.example.com/mcp")
            # One private address among public ones is enough to refuse.
            with resolving_to("93.184.216.34", "10.0.0.1"), self.assertRaises(safety.UnsafeURLError):
                self.check("https://mixed.example.com/mcp")

    def test_form_is_checked_before_resolving(self):
        with patch.dict(os.environ, {"MCP_ALLOW_PRIVATE_URLS": "false"}):
            for url in ("http://mcp.example.com/mcp", "ftp://x/y", "https://u:p@mcp.example.com/mcp", "https:///mcp"):
                with self.assertRaises(safety.UnsafeURLError, msg=url):
                    self.check(url)


class SecretStorageTests(unittest.TestCase):
    def test_round_trip_and_wrong_key(self):
        with patch.dict(os.environ, {"MCP_SECRET_KEY": Fernet.generate_key().decode()}):
            blob = store.encrypt_secret({"header_name": "Authorization", "header_value": "Bearer abc"})
            self.assertNotIn(b"abc", blob)
            self.assertEqual(store.decrypt_secret(blob)["header_value"], "Bearer abc")
        with patch.dict(os.environ, {"MCP_SECRET_KEY": Fernet.generate_key().decode()}):
            with self.assertRaises(store.SecretKeyMissing):
                store.decrypt_secret(blob)
        with patch.dict(os.environ, {"MCP_SECRET_KEY": ""}), self.assertRaises(store.SecretKeyMissing):
            store.encrypt_secret({"header_value": "x"})

    def test_default_policies(self):
        self.assertEqual(store.default_policy({"read_only": True}), "allow")
        self.assertEqual(store.default_policy({"read_only": False}), "ask")

    def test_multiple_headers_are_sent_and_old_single_header_connections_still_work(self):
        multiple = {"auth_type": "header", "secret": {"headers": {
            "x-api-host": "linkedin-api8.p.rapidapi.com", "x-api-key": "secret"}}}
        legacy = {"auth_type": "header", "secret": {"header_name": "Authorization", "header_value": "Bearer x"}}
        self.assertEqual(session_module._headers(multiple), {
            "x-api-host": "linkedin-api8.p.rapidapi.com", "x-api-key": "secret"})
        self.assertEqual(session_module._headers(legacy), {"Authorization": "Bearer x"})

    def test_mcp_image_content_and_direct_image_urls_are_returned_separately(self):
        image_block = session_module.types.ImageContent(mimeType="image/png", data=b64encode(b"small image").decode())
        text_block = session_module.types.TextContent(text="Created https://img.example.test/result.jpg?token=abc")
        signed_url = session_module.types.TextContent(text="Image URL: https://cdn.example.test/render?id=123")
        result = types.SimpleNamespace(content=[text_block, signed_url, image_block], structured_content=None, is_error=False)
        text, is_error, images = session_module.result_text(result)
        self.assertFalse(is_error)
        self.assertIn("displayed separately", text)
        self.assertEqual(len(images), 3)
        self.assertTrue(images[0]["src"].startswith("data:image/png;base64,"))
        self.assertEqual(images[1]["src"], "https://img.example.test/result.jpg?token=abc")
        self.assertEqual(images[2]["src"], "https://cdn.example.test/render?id=123")

    def test_mcp_image_payload_size_is_bounded_and_non_image_urls_are_ignored(self):
        huge = session_module.types.ImageContent(mimeType="image/png",
                                                 data=b64encode(b"x" * (session_module.MAX_IMAGE_BYTES + 1)).decode())
        result = types.SimpleNamespace(content=[huge], structured_content=None, is_error=False)
        self.assertEqual(session_module.result_text(result)[2], [])
        self.assertFalse(session_module._is_image_url("https://example.test/page"))


CONNECTION = {"id": "conn-1", "name": "Notes", "url": "https://notes.example.com/mcp", "auth_type": "none",
              "secret": None}


def registry(policy):
    tool = {"name": "create_note", "title": "Create note", "description": "", "policy": policy,
            "input_schema": {"type": "object"}}
    return [{"name": "c0__create_note"}], {"c0__create_note": (CONNECTION, tool)}


def gemini_rounds(*rounds):
    """Fake stream_gemini_parts: each call yields the next round's parts."""
    calls = iter(rounds)
    seen = []

    def fake(contents, declarations):
        seen.append((list(contents), declarations))
        return iter(next(calls))
    return fake, seen


CALL = [{"functionCall": {"name": "c0__create_note", "args": {"name": "x"}, "id": "call-1"},
         "thoughtSignature": "sig"}]
ANSWER = [{"text": "Done."}]


class ToolLoopTests(unittest.TestCase):
    def test_structured_tool_excerpts_and_verifier_share_the_same_source(self):
        from app.services.answer_verification import check_citations

        title = "Senior Software Engineer – MERN Stack"
        result = json.dumps({"jobs": [{"title": title, "company": "Walkwel Technology"}]})
        declarations, tools = registry("allow")
        fake, seen = gemini_rounds(CALL, ANSWER)

        async def main():
            return [event async for event in agent.answer_with_tools("user-1", "Find jobs", "", declarations, tools)]

        with patch.object(agent, "stream_gemini_parts", fake), \
             patch.object(agent, "_run_tool", AsyncMock(return_value=(result, False, []))):
            events = asyncio.run(main())
        reply = seen[1][0][2]["parts"][0]["functionResponse"]["response"]
        self.assertEqual(reply["result"], result)
        self.assertNotIn("citation_excerpts", reply)
        evidence = [source for kind, data in events if kind == "evidence" for source in data["sources"]]
        self.assertEqual(evidence[0]["id"], reply["source_id"])
        answer = 'Role [1].\n```citations\n' + json.dumps([
            {"n": 1, "source": reply["source_id"], "quote": title}]) + '\n```'
        self.assertTrue(check_citations(answer, "", [], evidence)[1][0]["verified"])

    def collect(self, policy, decide=None, user="user-1"):
        declarations, tools = registry(policy)
        fake, seen = gemini_rounds(CALL, ANSWER)
        run = AsyncMock(return_value=("Saved x", False, []))

        async def main():
            events = []
            async for name, data in agent.answer_with_tools(user, "make a note", "ctx", declarations, tools):
                events.append((name, data))
                if name == "approval_required" and decide is not None:
                    decide(data["id"])
            return events
        with patch.object(agent, "stream_gemini_parts", fake), patch.object(agent, "_run_tool", run):
            events = asyncio.run(main())
        return events, run, seen

    def test_allowed_tool_runs_and_its_result_goes_back_to_the_model(self):
        events, run, seen = self.collect("allow")
        statuses = [data.get("status") for name, data in events if name == "tool_call"]
        self.assertEqual(statuses, ["running", "done"])
        self.assertEqual(events[-1], ("delta", {"text": "Done."}))
        run.assert_awaited_once()
        second_round = seen[1][0]
        self.assertEqual(second_round[1]["parts"], CALL)  # model parts (with signature) sent back
        reply = second_round[2]["parts"][0]["functionResponse"]
        self.assertEqual((reply["name"], reply["id"], reply["response"]["result"]),
                         ("c0__create_note", "call-1", "Saved x"))
        self.assertIn("untrusted", reply["response"]["source"])

    def test_tool_images_stream_separately_from_the_answer_text(self):
        declarations, tools = registry("allow")
        fake, _ = gemini_rounds(CALL, ANSWER)
        image = {"src": "https://images.example.test/generated.webp", "alt": "Generated image"}

        async def main():
            return [event async for event in agent.answer_with_tools("user-1", "Generate an image", "", declarations, tools)]

        with patch.object(agent, "stream_gemini_parts", fake), \
             patch.object(agent, "_run_tool", AsyncMock(return_value=("Image generated.", False, [image]))):
            events = asyncio.run(main())
        generated = next(data for name, data in events if name == "generated_images")
        tool = next(data for name, data in events if name == "tool_call" and data["status"] == "running")
        self.assertEqual(generated, {"images": [image], "tool_call_id": tool["id"]})
        self.assertEqual(events[-1], ("delta", {"text": "Done."}))

    def test_ask_waits_for_approval_then_runs(self):
        events, run, _ = self.collect("ask", decide=lambda i: agent.resolve_approval("user-1", i, True))
        names = [name for name, _ in events]
        self.assertLess(names.index("approval_required"), names.index("delta"))
        statuses = [data.get("status") for name, data in events if name == "tool_call"]
        self.assertEqual(statuses, ["awaiting_approval", "running", "done"])
        run.assert_awaited_once()

    def test_declined_tool_never_runs(self):
        events, run, seen = self.collect("ask", decide=lambda i: agent.resolve_approval("user-1", i, False))
        statuses = [data.get("status") for name, data in events if name == "tool_call"]
        self.assertEqual(statuses, ["awaiting_approval", "denied"])
        run.assert_not_awaited()
        self.assertIn("declined", seen[1][0][2]["parts"][0]["functionResponse"]["response"]["result"])

    def test_another_user_cannot_approve(self):
        outcome = {}

        def decide(approval_id):
            outcome["other"] = agent.resolve_approval("intruder", approval_id, True)
            outcome["owner"] = agent.resolve_approval("user-1", approval_id, False)
        _, run, _ = self.collect("ask", decide=decide)
        self.assertEqual(outcome, {"other": False, "owner": True})
        run.assert_not_awaited()

    def test_last_round_offers_no_tools(self):
        declarations, tools = registry("allow")
        rounds = [CALL] * agent.MAX_ROUNDS + [ANSWER]
        fake, seen = gemini_rounds(*rounds)

        async def main():
            return [e async for e in agent.answer_with_tools("user-1", "q", "c", declarations, tools)]
        with patch.object(agent, "stream_gemini_parts", fake), \
             patch.object(agent, "_run_tool", AsyncMock(return_value=("ok", False, []))):
            asyncio.run(main())
        self.assertEqual(len(seen), agent.MAX_ROUNDS + 1)
        self.assertEqual(seen[-1][1], [])

    def test_max_tokens_continues_once_without_repeating_web_search(self):
        query = "Find hybrid software developer jobs in Chandigarh"
        search_call = {"functionCall": {"id": "search1", "name": agent.WEB_SEARCH_TOOL["name"],
                        "args": {"query": query}}}
        partial = "To land a Software Developer role in the Chandigarh region,"
        continuation = " here are companies with relevant openings and salary details."
        fake, seen = gemini_rounds(
            [search_call],
            [{"text": partial}, {"finishReason": "MAX_TOKENS"}],
            [{"text": continuation}, {"finishReason": "STOP"}],
        )

        async def main():
            return [event async for event in agent.answer_with_tools("user-1", query, "", [], {})]

        with (
            patch.object(agent, "stream_gemini_parts", fake),
            patch.object(agent, "google_search_ready", return_value=False),
            patch.object(agent, "web_search_available", return_value=True),
            patch.object(agent, "image_search_configured", return_value=False),
            patch.object(agent, "search_web", return_value=("Found jobs", [], [])) as search,
            self.assertLogs("app.mcp_client.agent", level="INFO") as logs,
        ):
            events = asyncio.run(main())

        deltas = [data["text"] for kind, data in events if kind == "delta"]
        self.assertEqual(deltas, [partial, continuation])
        self.assertEqual(len(seen), 3)
        self.assertEqual(seen[2][1], [])
        self.assertEqual(seen[2][0][-2], {"role": "model", "parts": [{"text": partial}]})
        self.assertIn("Continue from where it stopped", seen[2][0][-1]["parts"][0]["text"])
        search.assert_called_once_with(query)
        self.assertIn("reason=MAX_TOKENS", " ".join(logs.output))

    def test_second_max_tokens_surfaces_incomplete_answer_instead_of_looping(self):
        fake, seen = gemini_rounds(
            [{"text": "First partial"}, {"finishReason": "MAX_TOKENS"}],
            [{"text": "Second partial"}, {"finishReason": "MAX_TOKENS"}],
        )

        async def main():
            return [event async for event in agent.answer_with_tools("user-1", "q", "", [], {})]

        with (
            patch.object(agent, "stream_gemini_parts", fake),
            patch.object(agent, "image_search_configured", return_value=False),
            self.assertLogs("app.mcp_client.agent", level="WARNING"),
        ):
            with self.assertRaises(agent.IncompleteAnswerError):
                asyncio.run(main())
        self.assertEqual(len(seen), 2)


class ToolSchemaTests(unittest.TestCase):
    # Zapier describes "any JSON value" with a $ref that loops back on itself; Gemini rejects that.
    ANY_JSON = {"anyOf": [{"type": "string"}, {"type": "null"},
                          {"type": "array", "items": {"$ref": "#/$defs/json"}},
                          {"type": "object", "additionalProperties": {"$ref": "#/$defs/json"}}]}

    def test_recursive_definitions_are_inlined_and_loops_left_open(self):
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
                  "$defs": {"json": self.ANY_JSON, "name": {"type": "string"}},
                  "required": ["action"],
                  "properties": {"action": {"$ref": "#/$defs/name"}, "params": {"$ref": "#/$defs/json"}}}
        clean = agent._clean_schema(schema)
        text = json.dumps(clean)
        self.assertNotIn("$ref", text)
        self.assertNotIn("$defs", text)
        self.assertNotIn("$schema", text)
        self.assertEqual(clean["properties"]["action"], {"type": "string"})
        params = clean["properties"]["params"]["anyOf"]
        self.assertEqual(params[2], {"type": "array", "items": {}})
        self.assertEqual(params[3], {"type": "object", "additionalProperties": {}})

    def test_a_rejected_tool_list_does_not_lose_the_answer(self):
        declarations, tools = registry("allow")
        seen = []

        def gemini(contents, offered):
            seen.append([item["name"] for item in offered])
            if len(seen) == 1:
                raise requests.HTTPError(response=Mock(status_code=400, text="ref loops are not supported"))
            return iter(ANSWER)

        async def main():
            return [event async for event in agent.answer_with_tools("user-1", "q", "c", declarations, tools)]
        with patch.object(agent, "stream_gemini_parts", gemini), \
             patch.object(agent, "backup_configured", return_value=False), \
             patch.object(agent, "image_search_configured", return_value=False), \
             patch.object(agent, "web_search_available", return_value=False), \
             self.assertLogs("app.mcp_client.agent", level="WARNING"):
            events = asyncio.run(main())
        self.assertEqual(seen, [["c0__create_note"], []])
        self.assertEqual(events[-1], ("delta", {"text": "Done."}))
        self.assertEqual(events[0][1]["status"], "error")
        self.assertEqual(events[0][1]["server"], "Notes")
        self.assertIn("No action was executed", events[0][1]["summary"])


class ConnectionsAPITests(unittest.TestCase):
    def setUp(self):
        backend.app.dependency_overrides[current_user] = lambda: "user-1"
        self.addCleanup(backend.app.dependency_overrides.clear)
        self.client = TestClient(backend.app)

    def test_unsafe_url_is_refused_with_its_reason(self):
        with patch.object(store, "count_connections", AsyncMock(return_value=0)), \
             patch.object(connections, "fetch_tools", AsyncMock(side_effect=safety.UnsafeURLError("private network"))):
            response = self.client.post("/mcp-connections", json={"name": "X", "url": "https://10.0.0.1/mcp"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("private network", response.json()["detail"])

    def test_header_auth_needs_a_value_and_secrets_are_never_returned(self):
        with patch.object(store, "count_connections", AsyncMock(return_value=0)):
            response = self.client.post("/mcp-connections", json={
                "name": "X", "url": "https://mcp.example.com/mcp", "auth_type": "header", "header_value": " "})
        self.assertEqual(response.status_code, 422)
        listed = {**CONNECTION, "secret": {"header_value": "Bearer abc"}, "tools": []}
        with patch.object(store, "list_connections", AsyncMock(return_value=[listed])):
            body = self.client.get("/mcp-connections").json()
        self.assertNotIn("secret", body["connections"][0])
        self.assertNotIn("Bearer abc", str(body))

    def test_policy_for_unknown_tool_is_rejected(self):
        existing = {**CONNECTION, "tools": [{"name": "read_note", "policy": "allow"}]}
        with patch.object(store, "get_connection", AsyncMock(return_value=existing)):
            response = self.client.patch("/mcp-connections/conn-1", json={"tool_policies": {"delete_all": "allow"}})
        self.assertEqual(response.status_code, 422)

    def test_too_many_connections(self):
        with patch.object(store, "count_connections", AsyncMock(return_value=store.MAX_CONNECTIONS)):
            response = self.client.post("/mcp-connections", json={"name": "X", "url": "https://mcp.example.com/mcp"})
        self.assertEqual(response.status_code, 400)

    def test_unknown_approval_is_404(self):
        response = self.client.post("/chat/approvals/nope", json={"approve": True})
        self.assertEqual(response.status_code, 404)


class OAuthFlowTests(unittest.TestCase):
    def test_reconnect_starts_a_flow_for_the_existing_oauth_connection(self):
        connection = {**CONNECTION, "auth_type": "oauth"}
        backend.app.dependency_overrides[current_user] = lambda: "user-1"
        self.addCleanup(backend.app.dependency_overrides.clear)
        with patch.object(store, "get_connection", AsyncMock(return_value=connection)), \
             patch.object(store, "encrypt_secret"), \
             patch.object(oauth, "start_flow", AsyncMock(return_value=("flow-1", "https://login.example.com"))) as start:
            response = TestClient(backend.app).post("/mcp-connections/conn-1/oauth/reconnect")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"flow_id": "flow-1", "authorization_url": "https://login.example.com"})
        start.assert_awaited_once_with("user-1", "Notes", "https://notes.example.com/mcp", connection_id="conn-1")

    def test_successful_tool_call_clears_an_old_connection_error(self):
        connection = {**CONNECTION, "last_error": "Sign in again"}
        session = Mock()
        session_context = Mock()
        session_context.__aenter__ = AsyncMock(return_value=session)
        session_context.__aexit__ = AsyncMock(return_value=None)
        with patch.object(agent, "open_session", return_value=session_context), \
             patch.object(agent, "call_tool", AsyncMock(return_value=("ok", False, []))), \
             patch.object(store, "update_connection", AsyncMock()) as update:
            result = asyncio.run(agent._run_tool("user-1", connection, {"name": "read"}, {}))
        self.assertEqual(result, ("ok", False, []))
        self.assertIsNone(connection["last_error"])
        update.assert_awaited_once_with("user-1", "conn-1", last_error=None)

    def test_nested_reauthorization_reaches_tool_status_and_is_not_retried(self):
        error = ExceptionGroup("transport", [ExceptionGroup("session", [oauth.ReauthorizationRequired("Sign in again")])])
        connection = {**CONNECTION, "auth_type": "oauth"}
        self.assertTrue(oauth.needs_reauthorization(error))
        with patch.object(agent, "provider_for", return_value=Mock()), \
             patch.object(agent, "open_session", side_effect=error) as connect, \
             patch.object(store, "update_connection", AsyncMock()) as update:
            first = asyncio.run(agent._run_tool("user-1", connection, {"name": "discover"}, {}))
            second = asyncio.run(agent._run_tool("user-1", connection, {"name": "inspect"}, {}))
        self.assertTrue(first[1])
        self.assertIn("reauthorization", first[0])
        self.assertEqual(first, second)
        self.assertEqual(connect.call_count, 1)
        update.assert_awaited_once()

    def test_unknown_state_is_ignored_and_callback_page_is_escaped(self):
        client = TestClient(backend.app)
        page = client.get("/mcp-connections/oauth/callback", params={"state": "nope", "code": "c"})
        self.assertEqual(page.status_code, 200)
        self.assertIn("expired", page.text)

        async def main():
            flow = oauth.Flow("user-1", "<img src=x onerror=alert(1)>", "https://mcp.example.com/mcp")
            oauth._flows["state-1"] = flow
            return flow
        flow = asyncio.run(main())
        try:
            self.assertIsNone(oauth.finish_flow("other-state", "code", None, None))
            self.assertIsNone(oauth.flow_status("intruder", "state-1"))
            self.assertEqual(oauth.flow_status("user-1", "state-1")["status"], "pending")
            with patch.object(oauth, "finish_flow", return_value=flow):
                page = client.get("/mcp-connections/oauth/callback", params={"state": "state-1", "code": "c"})
            self.assertNotIn("<img", page.text)
            self.assertIn("&lt;img", page.text)
        finally:
            oauth._flows.pop("state-1", None)

    def test_tokens_are_kept_in_the_connection_secret(self):
        from mcp.shared.auth import OAuthToken
        storage = oauth.SecretStorage({"client_info": {"client_id": "abc", "redirect_uris": ["https://x/cb"]}})

        async def main():
            await storage.set_tokens(OAuthToken(access_token="tok", token_type="Bearer", expires_in=60))
            return await storage.get_tokens(), await storage.get_client_info()
        tokens, info = asyncio.run(main())
        self.assertEqual((tokens.access_token, info.client_id), ("tok", "abc"))
        self.assertEqual(storage.secret["tokens"]["access_token"], "tok")

    def test_every_outgoing_request_is_checked(self):
        import httpx2

        async def main():
            await session_module._guard_request(httpx2.Request("GET", "https://169.254.169.254/latest/meta-data"))
        with patch.dict(os.environ, {"MCP_ALLOW_PRIVATE_URLS": "false"}), resolving_to("169.254.169.254"), \
             self.assertRaises(safety.UnsafeURLError):
            asyncio.run(main())


if __name__ == "__main__":
    unittest.main()
