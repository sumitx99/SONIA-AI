"""Sonia's MCP server over the real Streamable HTTP endpoint; auth and DB are fakes."""

import importlib
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

import jwt
from fastapi.testclient import TestClient

# Avoid loading Docling models during tests (same stub as the API tests).
parser = types.ModuleType("app.docling_utils")
parser.process_pdf_with_docling = Mock()
parser.docling_enabled = Mock(return_value=False)
sys.modules.setdefault("app.docling_utils", parser)
backend = importlib.import_module("app.app")
server = importlib.import_module("app.mcp_server.server")
tools = importlib.import_module("app.mcp_server.tools")

HEADERS = {"Accept": "application/json, text/event-stream", "Authorization": "Bearer good-token"}


def fake_claims(token):
    if token != "good-token":
        raise jwt.InvalidTokenError("bad")
    return {"sub": "user-1", "client_id": "claude-client", "exp": 4_000_000_000,
            "iss": "https://example.supabase.co/auth/v1"}


class MCPServerTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(server, "verify_claims", side_effect=fake_claims)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The MCP endpoint only accepts its configured hosts (DNS-rebinding protection).
        self.client = TestClient(backend.app, base_url="http://localhost:8000")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def rpc(self, method, params=None, headers=HEADERS):
        return self.client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})

    def initialize(self):
        response = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                           "clientInfo": {"name": "test", "version": "1"}})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["result"]

    def call(self, name, arguments):
        self.initialize()
        response = self.rpc("tools/call", {"name": name, "arguments": arguments})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["result"]

    def test_missing_or_bad_token_points_clients_to_the_login_metadata(self):
        for headers in ({"Accept": HEADERS["Accept"]}, {**HEADERS, "Authorization": "Bearer stolen"}):
            response = self.rpc("initialize", headers=headers)
            self.assertEqual(response.status_code, 401)
            self.assertIn("resource_metadata=", response.headers["www-authenticate"])
        metadata = self.client.get("/.well-known/oauth-protected-resource/mcp").json()
        self.assertTrue(metadata["resource"].endswith("/mcp"))
        self.assertTrue(metadata["authorization_servers"][0].endswith("/auth/v1"))

    def test_unknown_host_is_refused(self):
        other = TestClient(backend.app, base_url="http://evil.example")
        response = other.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(response.status_code, 421)

    def test_lists_four_read_only_tools(self):
        self.assertEqual(self.initialize()["serverInfo"]["name"], "Sonia")
        listed = self.rpc("tools/list").json()["result"]["tools"]
        self.assertEqual(sorted(tool["name"] for tool in listed),
                         ["ask_sonia", "get_image", "list_documents", "search_documents"])
        self.assertTrue(all(tool["annotations"]["readOnlyHint"] for tool in listed))

    def test_tools_only_see_the_token_owners_documents(self):
        owned = AsyncMock(side_effect=lambda user, ids=None: [7] if ids is None else [i for i in ids if i == 7])
        search = AsyncMock(return_value=[{"document_id": 7, "filename": "a.pdf", "text": "passage"}])
        with patch.object(tools, "owned_document_ids", owned), \
             patch.object(tools, "search_document_chunks", search), \
             patch.object(tools, "get_embedding", return_value=[0.1]):
            result = self.call("search_documents", {"query": "attention", "document_ids": [7, 8]})
        self.assertFalse(result.get("isError"), result)
        owned.assert_awaited_with("user-1", [7, 8])
        self.assertEqual(search.call_args.args[1], [7])  # document 8 belongs to someone else
        self.assertIn("passage", str(result))

    def test_list_documents_uses_the_signed_in_user(self):
        listing = AsyncMock(return_value=[{"id": 7, "filename": "a.pdf", "chat_id": None, "uploaded_at": None}])
        with patch.object(tools, "list_user_documents", listing):
            result = self.call("list_documents", {})
        listing.assert_awaited_once_with("user-1")
        self.assertIn("a.pdf", str(result))

    def test_get_image_refuses_someone_elses_document(self):
        with patch.object(tools, "owned_document_ids", AsyncMock(return_value=[])), \
             patch.object(tools, "find_document_images", AsyncMock()) as find:
            result = self.call("get_image", {"document_id": 8, "page_number": 1})
        self.assertTrue(result["isError"])
        find.assert_not_awaited()

    def test_ask_sonia_answers_from_the_users_context(self):
        context = AsyncMock(return_value=("Document text", {"images": [], "image_status": "not_requested",
                                                            "image_notice": None}))
        with patch.object(backend, "_answer_context", context), \
             patch("app.llm.get_llm_response", return_value="**Grounded** answer"):
            result = self.call("ask_sonia", {"question": "What is attention?"})
        self.assertEqual(context.call_args.args[4], "user-1")
        self.assertIn("Grounded", str(result))


if __name__ == "__main__":
    unittest.main()
