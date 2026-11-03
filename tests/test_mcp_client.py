"""Sonia as an MCP client: URL safety, secret storage, the tool loop and approvals."""

import asyncio
import importlib
import os
import socket
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

parser = types.ModuleType("app.docling_utils")
parser.process_pdf_with_docling = Mock()
parser.docling_enabled = Mock(return_value=False)
sys.modules.setdefault("app.docling_utils", parser)
backend = importlib.import_module("app.app")
agent = importlib.import_module("app.mcp_client.agent")
connections = importlib.import_module("app.mcp_client.connections")
safety = importlib.import_module("app.mcp_client.safety")
store = importlib.import_module("app.mcp_client.store")


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
    def collect(self, policy, decide=None, user="user-1"):
        declarations, tools = registry(policy)
        fake, seen = gemini_rounds(CALL, ANSWER)
        run = AsyncMock(return_value=("Saved x", False))

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
             patch.object(agent, "_run_tool", AsyncMock(return_value=("ok", False))):
            asyncio.run(main())
        self.assertEqual(len(seen), agent.MAX_ROUNDS + 1)
        self.assertEqual(seen[-1][1], [])


class ConnectionsAPITests(unittest.TestCase):
    def setUp(self):
        backend.app.dependency_overrides[backend.current_user] = lambda: "user-1"
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


if __name__ == "__main__":
    unittest.main()
