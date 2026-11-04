"""API contract tests; parsing, model calls, DB and R2 are external-service fakes."""

import importlib
import json
import sys
import types
import unittest

import requests
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from test_document_images import sample_pdf

# Avoid loading Docling models or making network calls during API tests.
parser = types.ModuleType("app.services.parsing.docling_utils")
parser.process_pdf_with_docling = Mock()
parser.docling_enabled = Mock(return_value=False)
original_parser = sys.modules.get("app.services.parsing.docling_utils")
sys.modules["app.services.parsing.docling_utils"] = parser
try:
    main = importlib.import_module("app.main")
    chat_api = importlib.import_module("app.api.chat")
    documents_api = importlib.import_module("app.api.documents")
    context = importlib.import_module("app.services.context")
    agent = importlib.import_module("app.mcp_client.agent")
    from app.core.auth import current_user
finally:
    if original_parser is None:
        sys.modules.pop("app.services.parsing.docling_utils", None)
    else:
        sys.modules["app.services.parsing.docling_utils"] = original_parser


class ImageAPITests(unittest.TestCase):
    def setUp(self):
        network = patch("requests.post", side_effect=AssertionError("External calls are disabled in tests"))
        network.start()
        self.addCleanup(network.stop)
        # No MCP connections, so answers don't touch the connections table.
        no_tools = patch.object(chat_api, "available_tools", AsyncMock(return_value=([], {})))
        no_tools.start()
        self.addCleanup(no_tools.stop)
        # Signed in as user-1, who owns only document 7.
        main.app.dependency_overrides[current_user] = lambda: "user-1"
        self.addCleanup(main.app.dependency_overrides.clear)
        # Answers and document routes both check ownership.
        for module in (context, documents_api):
            owned = patch.object(module, "owned_document_ids",
                                 side_effect=lambda user, ids=None: [7] if ids is None else [i for i in ids if i == 7])
            owned.start()
            self.addCleanup(owned.stop)
        self.client = TestClient(main.app)
        finish = patch.object(documents_api, "finish_upload")
        finish.start()
        self.addCleanup(finish.stop)
        self.image = {"image_id": "image-1", "document_id": 7, "page_number": 12,
                      "image_number": 2, "object_key": "private-image-key",
                      "search_text": "API architecture", "heading_path": ["Architecture"],
                      "text_before": "Before", "text_after": "After"}
        self.storage = Mock(expires_in=900)
        self.storage.sign.return_value = "https://example.test/signed-image"

    def chat(self, query, data=None, candidates=None, storage=None):
        candidates = [self.image] if candidates is None else candidates
        with patch.object(context, "get_embedding", return_value=[0.1]), \
             patch.object(context, "get_reranked_context", return_value="Document text") as text_search, \
             patch.object(agent, "stream_gemini_parts", return_value=iter([{"text": "An answer."}])) as llm, \
             patch.object(documents_api.R2ImageStorage, "from_env", return_value=storage or self.storage) as config, \
             patch.object(context, "find_document_images", return_value=candidates) as search, \
             patch.object(context, "rank_contexts", side_effect=lambda query, results, **kwargs: results):
            response = self.client.post("/chat", data={"query": query, **(data or {})})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), text_search, search, config, llm

    def test_explicit_image_request_returns_source_and_keeps_document_scope(self):
        response, text_search, search, _, llm = self.chat(
            "page 12 ki second image dikhao", {"document_ids": [7], "scope_documents": "true"},
        )
        self.assertEqual(response["image_status"], "ready")
        self.assertEqual(response["images"][0]["source_path"], "/documents/7/source#page=12")
        self.assertNotIn("object_key", response["images"][0])
        self.assertEqual(search.call_args.kwargs, {"document_ids": [7], "page_number": 12, "image_number": 2})
        self.assertEqual(text_search.call_args.kwargs["document_ids"], [7])
        self.assertIn("pixels have not been analyzed", llm.call_args.args[0][-1]["parts"][0]["text"])

    def test_plain_query_does_not_attach_images(self):
        response, _, search, config, _ = self.chat("Summarize the policy")
        self.assertEqual(response["images"], [])
        self.assertEqual(response["image_status"], "not_requested")
        search.assert_not_called()
        config.assert_not_called()

    def test_explicit_include_images_flag(self):
        response, _, search, _, _ = self.chat("Explain the architecture", {"include_images": "true"})
        self.assertEqual(response["image_status"], "ready")
        search.assert_called_once()

    def test_missing_exact_location_is_not_replaced_with_another_image(self):
        response, _, search, _, _ = self.chat("Show image 9 on page 99", candidates=[])
        self.assertEqual(response["images"], [])
        self.assertEqual(response["image_status"], "not_found")
        self.assertEqual(search.call_args.kwargs["page_number"], 99)
        self.assertEqual(search.call_args.kwargs["image_number"], 9)

    def test_new_empty_chat_does_not_search_other_uploaded_documents(self):
        _, text_search, search, _, _ = self.chat("Show images", {"scope_documents": "true"}, candidates=[])
        self.assertEqual(text_search.call_args.kwargs["document_ids"], [])
        self.assertEqual(search.call_args.kwargs["document_ids"], [])

    def test_unscoped_chat_searches_only_the_users_documents(self):
        _, text_search, _, _, _ = self.chat("Summarize the policy")
        self.assertEqual(text_search.call_args.kwargs["document_ids"], [7])
        _, text_search, _, _, _ = self.chat("Summarize", {"document_ids": [7, 8], "scope_documents": "true"})
        self.assertEqual(text_search.call_args.kwargs["document_ids"], [7])

    def stream(self, query, parts, data=None):
        with patch.object(context, "get_embedding", return_value=[0.1]), \
             patch.object(context, "get_reranked_context", return_value="Document text"), \
             patch.object(agent, "backup_configured", return_value=False), \
             patch.object(agent, "stream_gemini_parts", return_value=iter(parts)) as llm:
            response = self.client.post("/chat/stream", data={"query": query, **(data or {})})
        events = []
        for frame in response.text.strip().split("\n\n"):
            lines = dict(line.split(": ", 1) for line in frame.splitlines())
            events.append((lines["event"], json.loads(lines["data"])))
        return response, events, llm

    def test_stream_sends_meta_then_text_pieces_then_done(self):
        parts = [{"text": "Self-"}, {"text": "attention "}, {"text": "**works**."}]
        response, events, llm = self.stream("Summarize", parts, {"document_ids": [7], "scope_documents": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual([name for name, _ in events], ["meta", "delta", "delta", "delta", "citations", "done"])
        self.assertEqual(events[0][1]["image_status"], "not_requested")
        self.assertEqual("".join(data["text"] for name, data in events if name == "delta"),
                         "Self-attention **works**.")
        prompt = llm.call_args.args[0][0]["parts"][0]["text"]
        self.assertIn("Document text", prompt)
        self.assertIn("Summarize", prompt)

    def test_stream_lists_web_sources_after_the_answer(self):
        grounding = {"groundingChunks": [
            {"web": {"uri": "https://example.com/a", "title": "Page A"}},
            {"web": {"uri": "https://example.com/a", "title": "Page A again"}},
            {"web": {"uri": "javascript:alert(1)", "title": "Not a web page"}}]}
        _, events, _ = self.stream("Summarize https://example.com/a",
                                   [{"text": "It says hi."}, {"groundingMetadata": grounding}])
        self.assertEqual([name for name, _ in events], ["meta", "delta", "sources", "citations", "done"])
        self.assertEqual(events[2][1], {"sources": [{"title": "Page A", "url": "https://example.com/a"}]})

    def test_stream_says_so_when_the_model_writes_nothing(self):
        _, events, _ = self.stream("Summarize", [])
        self.assertEqual([name for name, _ in events], ["meta", "delta", "done"])
        self.assertEqual(events[1][1]["text"], chat_api.NO_ANSWER)

    def test_stream_reports_an_answer_cut_off_part_way(self):
        def broken():
            yield {"text": "Partial "}
            raise RuntimeError("connection reset")
        with self.assertLogs("app.api.chat", level="ERROR"):
            _, events, _ = self.stream("Summarize", broken())
        self.assertEqual([name for name, _ in events], ["meta", "delta", "error"])
        self.assertIn("interrupted", events[-1][1]["detail"])

    @staticmethod
    def gemini_fails(status, after=()):
        def parts():
            yield from after
            raise requests.HTTPError(response=Mock(status_code=status))
        return parts()

    def test_stream_falls_back_to_a_backup_model_when_gemini_is_out_of_quota(self):
        backup = Mock(return_value=iter([("model", "openai/gpt-oss-120b"), ("text", "Backup "), ("text", "answer.")]))
        with patch.object(chat_api, "backup_configured", return_value=True), \
             patch.object(chat_api, "stream_backup_answer", backup), \
             self.assertLogs("app.api.chat", level="WARNING"):
            _, events, _ = self.stream("Summarize", self.gemini_fails(429))
        self.assertEqual([name for name, _ in events], ["meta", "delta", "delta", "citations", "done"])
        self.assertEqual("".join(data["text"] for name, data in events if name == "delta"), "Backup answer.")
        self.assertEqual(backup.call_args.args, ("Summarize", "Document text"))

    def test_an_answer_cut_off_part_way_is_not_restarted_by_the_backup(self):
        backup = Mock()
        with patch.object(chat_api, "backup_configured", return_value=True), \
             patch.object(chat_api, "stream_backup_answer", backup), \
             self.assertLogs("app.api.chat", level="ERROR"):
            _, events, _ = self.stream("Summarize", self.gemini_fails(503, after=[{"text": "Partial "}]))
        self.assertEqual([name for name, _ in events], ["meta", "delta", "error"])
        backup.assert_not_called()

    def test_quota_errors_say_so_instead_of_blaming_the_connection(self):
        with patch.object(chat_api, "backup_configured", return_value=False), \
             self.assertLogs("app.api.chat", level="ERROR"):
            _, events, _ = self.stream("Summarize", self.gemini_fails(429))
        self.assertEqual([name for name, _ in events], ["meta", "error"])
        self.assertIn("quota", events[-1][1]["detail"])

    def test_stream_requires_sign_in(self):
        main.app.dependency_overrides.clear()
        self.assertEqual(self.client.post("/chat/stream", data={"query": "hi"}).status_code, 401)

    def test_requests_without_a_token_are_rejected(self):
        main.app.dependency_overrides.clear()
        self.assertEqual(self.client.post("/chat", data={"query": "hi"}).status_code, 401)
        self.assertEqual(self.client.get("/documents/7/images",
                                         headers={"Authorization": "Bearer not-a-jwt"}).status_code, 401)

    def test_image_failures_keep_text_answers_available(self):
        with patch.object(context, "get_embedding", return_value=[0.1]), \
             patch.object(context, "get_reranked_context", return_value="Document text"), \
             patch.object(agent, "stream_gemini_parts", return_value=iter([{"text": "Text answer"}])), \
             patch.object(documents_api.R2ImageStorage, "from_env", side_effect=ValueError("Incomplete config")), \
             self.assertLogs("app.services.context", level="ERROR"):
            response = self.client.post("/chat", data={"query": "Show image"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["image_status"], "failed")
        self.assertEqual(response.json()["answer"], "Text answer")

    def test_source_endpoint_returns_original_pdf_and_missing_source_is_404(self):
        pdf = sample_pdf()
        with patch.object(documents_api, "get_document_source", return_value={"file": pdf, "source_key": None}) as get:
            response = self.client.get("/documents/7/source")
        get.assert_called_once_with(7, "user-1")
        self.assertEqual(response.content, pdf)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        with patch.object(documents_api, "get_document_source", return_value=None):
            self.assertEqual(self.client.get("/documents/999/source").status_code, 404)

    def test_source_in_r2_redirects_to_a_presigned_url(self):
        source = {"file": None, "source_key": "users/user-1/chats/chat-1/documents/7/source.pdf"}
        with patch.object(documents_api, "get_document_source", return_value=source), \
             patch.object(documents_api.R2ImageStorage, "from_env", return_value=self.storage):
            response = self.client.get("/documents/7/source", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "https://example.test/signed-image")
        self.storage.sign.assert_called_once_with(source["source_key"])

    def test_upload_rejects_unsafe_chat_id(self):
        response = self.client.post("/upload", data={"chat_id": "../other"},
                                    files={"file": ("guide.pdf", b"%PDF", "application/pdf")})
        self.assertEqual(response.status_code, 422)

    def test_image_refresh_stays_within_requested_document(self):
        with patch.object(documents_api.R2ImageStorage, "from_env", return_value=self.storage), \
             patch.object(documents_api, "find_document_images", return_value=[]) as search:
            response = self.client.get("/documents/7/images/image-1")
        self.assertEqual(response.status_code, 404)
        search.assert_called_once_with(document_ids=[7], image_id="image-1", limit=1)

    def test_other_users_documents_are_not_found(self):
        with patch.object(documents_api.R2ImageStorage, "from_env", return_value=self.storage), \
             patch.object(documents_api, "find_document_images", return_value=[self.image]) as search:
            self.assertEqual(self.client.get("/documents/8/images/image-1").status_code, 404)
            self.assertEqual(self.client.get("/documents/8/images").status_code, 404)
        search.assert_not_called()

    def test_list_endpoint_filters_location_and_validates_page(self):
        with patch.object(documents_api.R2ImageStorage, "from_env", return_value=self.storage), \
             patch.object(documents_api, "find_document_images", return_value=[self.image]) as search:
            response = self.client.get("/documents/7/images?page_number=12&image_number=2")
            self.assertEqual(response.status_code, 200)
            search.assert_called_once_with(document_ids=[7], page_number=12, image_number=2, limit=25)
            self.assertEqual(self.client.get("/documents/7/images?page_number=0").status_code, 422)

    def test_pdf_upload_runs_real_extraction_and_returns_image_count(self):
        prefix = "users/user-1/chats/chat-1/documents/7"
        self.storage.upload.return_value = f"{prefix}/images/stored.png"
        self.storage.upload_pdf.return_value = f"{prefix}/source.pdf"
        pdf = sample_pdf()
        with patch.object(documents_api, "insert_file", return_value=7) as insert, \
             patch.object(documents_api, "set_document_source_key") as set_key, \
             patch.object(documents_api, "insert_embeddings"), \
             patch.object(documents_api, "process_pdf_with_docling", return_value="# System Guide\nAPI text."), \
             patch.object(documents_api, "get_embeddings_batch", side_effect=lambda texts: [[0.1] for _ in texts]), \
             patch.object(documents_api.R2ImageStorage, "from_env", return_value=self.storage), \
             patch("app.services.images.image_pipeline.get_embeddings_batch", side_effect=lambda texts: [[0.1] for _ in texts]), \
             patch("app.services.images.image_pipeline.save_document_images") as save:
            response = self.client.post("/upload", data={"chat_id": "chat-1"},
                                        files={"file": ("guide.pdf", pdf, "application/pdf")})
        self.assertEqual(response.status_code, 200, response.text)
        insert.assert_called_once_with("guide.pdf", None, "chat-1", "user-1", None)
        self.storage.upload_pdf.assert_called_once_with(prefix, pdf)
        set_key.assert_called_once_with(7, f"{prefix}/source.pdf")
        self.assertEqual(self.storage.upload.call_args.args[0], prefix)
        self.assertEqual(response.json()["images_stored"], 1)
        self.assertEqual(response.json()["images_status"], "ready")
        image = save.call_args.args[1][0]
        self.assertIn("requests enter the API", image["text_before"])
        self.assertIn("worker processes the queue", image["text_after"])


if __name__ == "__main__":
    unittest.main()
