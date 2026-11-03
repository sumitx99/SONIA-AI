import json
import unittest
from unittest.mock import Mock, patch

import requests

from app.services.embeddings import _embed_request
import test_image_api as image_api
from test_document_images import sample_pdf

documents_api = image_api.documents_api


def response(status, payload=None):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload or {}).encode()
    result.headers["Content-Type"] = "application/json"
    return result


class EmbeddingRetryTests(unittest.TestCase):
    def test_transient_failures_retry_with_timeouts_without_keys_in_urls(self):
        with patch("app.services.embeddings.requests.post", side_effect=[response(429), response(503), response(200, {"ok": True})]) as post, \
             patch("app.services.embeddings.time.sleep") as sleep:
            self.assertEqual(_embed_request("embedContent", {}), {"ok": True})
        self.assertEqual(post.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertNotIn("key=", post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs["timeout"], (10, 60))

    def test_invalid_request_is_not_retried(self):
        with patch("app.services.embeddings.requests.post", return_value=response(400)) as post:
            with self.assertRaises(requests.HTTPError):
                _embed_request("embedContent", {})
        post.assert_called_once()

    def test_connection_failure_has_bounded_retries(self):
        with patch("app.services.embeddings.requests.post", side_effect=requests.Timeout) as post, \
             patch("app.services.embeddings.time.sleep"):
            with self.assertRaises(requests.Timeout):
                _embed_request("embedContent", {})
        self.assertEqual(post.call_count, 4)


class UploadReliabilityTests(unittest.TestCase):
    setUp = image_api.ImageAPITests.setUp
    def test_invalid_pdf_is_rejected_before_creating_a_document(self):
        with patch.object(documents_api, "insert_file") as insert:
            result = self.client.post("/upload", files={"file": ("bad.pdf", b"not PDF", "application/pdf")})
        self.assertEqual(result.status_code, 422)
        insert.assert_not_called()

    def test_retry_returns_completed_response_without_processing_again(self):
        cached = {"file_id": 7, "filename": "guide.pdf", "chunks_stored": 3}
        with patch.object(documents_api, "completed_upload", return_value=json.dumps(cached)) as find, \
             patch.object(documents_api, "_process_upload") as process:
            result = self.client.post("/upload", data={"request_id": "retry-1"},
                                      files={"file": ("guide.pdf", sample_pdf(), "application/pdf")})
        self.assertEqual(result.json(), cached)
        find.assert_called_once_with("user-1", "retry-1")
        process.assert_not_called()

    def test_failed_embedding_removes_incomplete_document_and_its_objects(self):
        with patch.object(documents_api, "insert_file", return_value=7), \
             patch.object(documents_api, "set_document_source_key"), \
             patch.object(documents_api, "delete_document") as delete, \
             patch.object(documents_api.R2ImageStorage, "from_env", return_value=self.storage), \
             patch.object(documents_api, "process_pdf_with_docling", return_value="PDF text"), \
             patch.object(documents_api, "get_embeddings_batch", side_effect=requests.Timeout), \
             self.assertLogs("app.api.documents", level="WARNING"):
            result = self.client.post("/upload", files={"file": ("guide.pdf", sample_pdf(), "application/pdf")})
        self.assertEqual(result.status_code, 503)
        delete.assert_awaited_once_with(7)
        self.storage.delete_upload.assert_called_once()
