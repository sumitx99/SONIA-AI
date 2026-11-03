import asyncio
import os
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch

from app.services.images.image_db import find_document_images, save_document_images
from app.services.images.image_pipeline import image_attachments, image_caption, ingest_document_images
from app.services.images.image_storage import R2ImageStorage, document_prefix
from app.core.db import search_embeddings


class FakePool:
    """Stands in for an asyncpg pool; records whether the transaction ended in an error."""

    def __init__(self):
        self.conn = AsyncMock()
        self.conn.fetch.return_value = []
        self.transaction_error = None

        @asynccontextmanager
        async def transaction():
            try:
                yield
            except Exception as error:
                self.transaction_error = error
                raise

        self.conn.transaction = transaction

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


class ImagePipelineTests(unittest.TestCase):
    def image(self):
        return {"image_id": "unique-image", "page_number": 2, "image_number": 1,
                "data": b"png", "extension": "png", "content_type": "image/png",
                "search_text": "API architecture before and after text"}

    def test_ingestion_links_uploaded_key_to_searchable_metadata(self):
        storage = Mock()
        storage.upload.return_value = "documents/7/images/unique-image.png"
        image = self.image()
        with patch("app.services.images.image_pipeline.extract_document_images", return_value=[image]), \
             patch("app.services.images.image_pipeline.get_embeddings_batch", return_value=[[0.1, 0.2]]) as embed, \
             patch("app.services.images.image_pipeline.save_document_images") as save:
            self.assertEqual(asyncio.run(ingest_document_images(7, b"pdf", "markdown", storage, "users/u/chats/c/documents/7")), 1)
            embed.assert_called_once_with([image["search_text"]])
            save.assert_called_once_with(7, [image], [[0.1, 0.2]])
            self.assertEqual(image["object_key"], storage.upload.return_value)

    def test_failed_database_write_cleans_up_uploaded_objects(self):
        storage = Mock()
        storage.upload.return_value = "uploaded-key"
        with patch("app.services.images.image_pipeline.extract_document_images", return_value=[self.image()]), \
             patch("app.services.images.image_pipeline.get_embeddings_batch", return_value=[[0.1]]), \
             patch("app.services.images.image_pipeline.save_document_images", side_effect=RuntimeError("DB failed")):
            with self.assertRaises(RuntimeError):
                asyncio.run(ingest_document_images(7, b"pdf", "", storage, "users/u/chats/c/documents/7"))
        storage.delete.assert_called_once_with("uploaded-key")

    def test_embedding_mismatch_does_not_upload_anything(self):
        storage = Mock()
        with patch("app.services.images.image_pipeline.extract_document_images", return_value=[self.image()]), \
             patch("app.services.images.image_pipeline.get_embeddings_batch", return_value=[]):
            with self.assertRaises(ValueError):
                asyncio.run(ingest_document_images(7, b"pdf", "", storage, "users/u/chats/c/documents/7"))
        storage.upload.assert_not_called()

    def test_empty_document_scope_cannot_search_other_documents(self):
        with patch("app.services.images.image_db.get_pool") as image_pool, patch("app.core.db.get_pool") as text_pool:
            self.assertEqual(asyncio.run(find_document_images([0.1], document_ids=[])), [])
            self.assertEqual(asyncio.run(search_embeddings([0.1], document_ids=[])), [])
        image_pool.assert_not_called()
        text_pool.assert_not_called()

    def test_explicit_location_and_document_scope_are_sql_filters(self):
        pool = FakePool()
        with patch("app.services.images.image_db.ensure_image_schema"), \
             patch("app.services.images.image_db.get_pool", AsyncMock(return_value=pool)):
            asyncio.run(find_document_images([0.1], document_ids=[7, 8], page_number=12, image_number=2))
        sql, *values = pool.conn.fetch.call_args.args
        self.assertIn("document_id = ANY($1::int[])", sql)
        self.assertIn("page_number = $2", sql)
        self.assertIn("image_number = $3", sql)
        self.assertEqual(values, [[7, 8], 12, 2, [0.1], 25])

    def test_database_failure_rolls_back_the_entire_image_batch(self):
        pool = FakePool()
        pool.conn.executemany.side_effect = RuntimeError("insert failed")
        image = {**self.image(), "object_key": "key"}
        with patch("app.services.images.image_db.ensure_image_schema"), \
             patch("app.services.images.image_db.get_pool", AsyncMock(return_value=pool)):
            with self.assertRaises(RuntimeError):
                asyncio.run(save_document_images(7, [image], [[0.1]]))
        # The batch ran inside one transaction, which saw the error and rolled back.
        self.assertIsInstance(pool.transaction_error, RuntimeError)
        self.assertEqual(len(pool.conn.executemany.call_args.args[1]), 1)

    def test_response_signs_urls_without_leaking_storage_keys_or_bytes(self):
        storage = Mock(expires_in=900)
        storage.sign.return_value = "https://signed.example/image"
        result = image_attachments([{**self.image(), "document_id": 7, "object_key": "private-key"}], storage)[0]
        self.assertEqual(result["url"], "https://signed.example/image")
        self.assertEqual(result["source_path"], "/documents/7/source#page=2")
        self.assertNotIn("data", result)
        self.assertNotIn("object_key", result)
        self.assertNotIn("search_text", result)

    def context(self, *texts):
        return [{"text": text, "page_number": 4, "block_number": i, "bbox": []} for i, text in enumerate(texts)]

    def test_response_shows_only_the_caption_not_surrounding_text(self):
        storage = Mock(expires_in=900)
        image = {**self.image(), "document_id": 7, "object_key": "k", "bbox": [1, 2, 3, 4],
                 "before_context": self.context("Scaled Dot-Product Attention", "Multi-Head Attention"),
                 "after_context": self.context(
                     "Figure 2: (left) Scaled Dot-Product Attention.\n(right) Multi-Head Attention.",
                     "query with all keys, divide each by √dk")}
        result = image_attachments([image], storage)[0]
        self.assertEqual(result["caption"],
                         "Figure 2: (left) Scaled Dot-Product Attention. (right) Multi-Head Attention.")
        for private in ("before_context", "after_context", "text_before", "text_after", "bbox"):
            self.assertNotIn(private, result)

    def test_caption_above_the_image_and_missing_caption(self):
        table = {"before_context": self.context("Intro text", "Table 1: Maximum path lengths."),
                 "after_context": self.context("Layer type  Complexity")}
        self.assertEqual(image_caption(table), "Table 1: Maximum path lengths.")
        plain = {"before_context": self.context("Figures show the results"),
                 "after_context": self.context("The encoder maps an input sequence.")}
        self.assertIsNone(image_caption(plain))

    def test_r2_disabled_and_partial_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(R2ImageStorage.from_env())
        with patch.dict(os.environ, {"R2_BUCKET_NAME": "test-bucket"}, clear=True):
            with self.assertRaisesRegex(ValueError, "Incomplete R2 configuration"):
                R2ImageStorage.from_env()

    def test_r2_upload_content_type_and_presigned_get(self):
        client = Mock()
        storage = R2ImageStorage(client, "private-bucket", 120)
        key = storage.upload("chats/chat-1/documents/7", self.image())
        self.assertEqual(key, "chats/chat-1/documents/7/images/unique-image.png")
        client.put_object.assert_called_once_with(Bucket="private-bucket", Key=key,
                                                   Body=b"png", ContentType="image/png")
        storage.sign(key)
        client.generate_presigned_url.assert_called_once_with(
            "get_object", Params={"Bucket": "private-bucket", "Key": key}, ExpiresIn=120,
        )

    def test_pdf_is_stored_under_its_chat_prefix(self):
        client = Mock()
        storage = R2ImageStorage(client, "private-bucket")
        key = storage.upload_pdf(document_prefix("user-1", "chat-1", 7), b"%PDF")
        self.assertEqual(key, "users/user-1/chats/chat-1/documents/7/source.pdf")
        client.put_object.assert_called_once_with(Bucket="private-bucket", Key=key,
                                                   Body=b"%PDF", ContentType="application/pdf")

    def test_chat_prefix_rejects_path_tricks_and_defaults_when_missing(self):
        self.assertEqual(document_prefix("user-1", None, 7), "users/user-1/chats/unassigned/documents/7")
        for bad in ("../other", "a/b", "", "x" * 65):
            with self.assertRaises(ValueError):
                document_prefix("user-1", bad, 7)
            with self.assertRaises(ValueError):
                document_prefix(bad or "a/b", "chat-1", 7)

    def test_ingestion_uploads_images_under_the_chat_prefix(self):
        storage = Mock()
        with patch("app.services.images.image_pipeline.extract_document_images", return_value=[self.image()]), \
             patch("app.services.images.image_pipeline.get_embeddings_batch", return_value=[[0.1]]), \
             patch("app.services.images.image_pipeline.save_document_images"):
            asyncio.run(ingest_document_images(7, b"pdf", "markdown", storage, "users/u/chats/chat-1/documents/7"))
        self.assertEqual(storage.upload.call_args.args[0], "users/u/chats/chat-1/documents/7")


if __name__ == "__main__":
    unittest.main()
