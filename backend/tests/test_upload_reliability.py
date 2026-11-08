import json
import unittest
from unittest.mock import Mock, patch

import requests
from asyncpg.exceptions import UniqueViolationError

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
        cached = {"file_id": 7, "filename": "guide.pdf", "chunks_stored": 3, "images_status": "processing"}
        self.document_status.return_value = {"images_status": "ready", "images_stored": 4}
        with patch.object(documents_api, "completed_upload", return_value=json.dumps(cached)) as find, \
             patch.object(documents_api, "_process_upload") as process:
            result = self.client.post("/upload", data={"request_id": "retry-1"},
                                      files={"file": ("guide.pdf", sample_pdf(), "application/pdf")})
        # Images that finished since the first response are reported as they are now.
        self.assertEqual(result.json(), {**cached, "images_status": "ready", "images_stored": 4})
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


class AbandonedUploadTests(unittest.TestCase):
    setUp = image_api.ImageAPITests.setUp

    def upload(self):
        return self.client.post("/upload", data={"request_id": "retry-1", "chat_id": "chat-1"},
                                files={"file": ("guide.pdf", sample_pdf(), "application/pdf")})

    def test_retry_clears_an_attempt_whose_process_died_and_starts_over(self):
        with patch.object(documents_api, "completed_upload", return_value=None), \
             patch.object(documents_api, "discard_unfinished_upload", return_value=[(5, "chat-1")]) as discard, \
             patch.object(documents_api, "_start_image_job"), \
             patch.object(documents_api, "insert_file", return_value=7) as insert, \
             patch.object(documents_api, "set_document_source_key"), \
             patch.object(documents_api, "insert_embeddings"), \
             patch.object(documents_api, "invalidate_conversations") as invalidate, \
             patch.object(documents_api, "ingest_document_images", return_value=0), \
             patch.object(documents_api.R2ImageStorage, "from_env", return_value=self.storage), \
             patch.object(documents_api, "process_pdf_with_docling", return_value="PDF text"), \
             patch.object(documents_api, "get_embeddings_batch", return_value=[[0.1]]), \
             self.assertLogs("app.api.documents", level="WARNING"):
            result = self.upload()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["file_id"], 7)
        discard.assert_awaited_once_with("user-1", "retry-1", documents_api.STALE_AFTER_SECONDS)
        self.storage.delete_upload.assert_called_once_with("users/user-1/chats/chat-1/documents/5")
        self.assertEqual(insert.await_args.args[4], "retry-1")
        invalidate.assert_awaited_once_with("user-1")

    def test_attempt_still_running_elsewhere_gets_a_conflict_not_a_server_error(self):
        with patch.object(documents_api, "completed_upload", return_value=None), \
             patch.object(documents_api, "discard_unfinished_upload", return_value=[]), \
             patch.object(documents_api, "insert_file", side_effect=UniqueViolationError("duplicate")), \
             patch.object(documents_api, "delete_document") as delete, \
             patch.object(documents_api.R2ImageStorage, "from_env", return_value=self.storage):
            result = self.upload()
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.headers["Retry-After"], str(documents_api.STALE_AFTER_SECONDS // 3))
        delete.assert_not_called()
        self.storage.delete_upload.assert_not_called()


class AbandonedUploadQueryTests(unittest.TestCase):
    def test_only_unanswered_rows_whose_heartbeat_stopped_are_deleted(self):
        import asyncio
        from unittest.mock import AsyncMock
        from test_image_pipeline import FakePool
        from app.core import db
        pool = FakePool()
        pool.conn.fetch.return_value = [{"id": 5, "chat_id": "chat-1"}]
        with patch.object(db, "ensure_document_schema", AsyncMock()), \
             patch.object(db, "get_pool", AsyncMock(return_value=pool)):
            self.assertEqual(asyncio.run(db.discard_unfinished_upload("user-1", "retry-1", 90)), [(5, "chat-1")])
        sql, *values = pool.conn.fetch.call_args.args
        self.assertIn("upload_response IS NULL", sql)
        self.assertIn("upload_heartbeat_at < now() - make_interval(secs => $3)", sql)
        self.assertEqual(values, ["user-1", "retry-1", 90.0])

    def test_status_marks_images_failed_when_their_worker_stopped(self):
        import asyncio
        from unittest.mock import AsyncMock
        from test_image_pipeline import FakePool
        from app.core import db
        pool = FakePool()
        pool.conn.fetchrow.return_value = {"images_status": "failed", "images_stored": None}
        with patch.object(db, "ensure_document_schema", AsyncMock()), \
             patch.object(db, "get_pool", AsyncMock(return_value=pool)):
            self.assertEqual(asyncio.run(db.document_status(7, 90)), {"images_status": "failed", "images_stored": 0})
        sql = pool.conn.fetchrow.call_args.args[0]
        self.assertIn("SET images_status = 'failed'", sql)
        self.assertIn("images_status = 'processing'", sql)
