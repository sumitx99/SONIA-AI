import asyncio
import io
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from PIL import Image

from app.services.images import web_images as images
from app.api import web_images as image_api, conversations
from app.mcp_client import agent
from test_image_pipeline import FakePool


IMAGE_ID = "a" * 64
CANDIDATE = {"title": "A bridge", "description": "A public bridge photograph", "author": "Test author",
             "license": "CC BY-SA 4.0", "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
             "provider": "Wikimedia Commons", "source_url": "https://commons.wikimedia.org/wiki/File:Bridge.jpg",
             "download_url": "https://thumb.wikimedia.org/bridge.jpg"}
ROW = {"user_id": "user-1", "image_id": IMAGE_ID, "object_key": "private-key", "source_url": CANDIDATE["source_url"],
       "metadata": {key: value for key, value in CANDIDATE.items() if key != "download_url"}}


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (100, 60), "blue").save(buffer, format="PNG")
    return buffer.getvalue()


class WebImagesTests(unittest.TestCase):
    def test_search_filters_missing_or_ineligible_licenses_and_html(self):
        info = {"thumburl": CANDIDATE["download_url"], "descriptionurl": CANDIDATE["source_url"],
                "extmetadata": {"License": {"value": "cc-by-sa-4.0"}, "LicenseUrl": {"value": CANDIDATE["license_url"]},
                                "LicenseShortName": {"value": "CC BY-SA 4.0"}, "Artist": {"value": "<b>Artist</b><script>bad</script>"}}}
        pages = [{"index": 1, "title": "File:Bridge.jpg", "imageinfo": [info]},
                 {"index": 2, "title": "File:Unknown.jpg", "imageinfo": [{**info, "extmetadata": {}}]},
                 {"index": 3, "title": "File:Private.jpg", "imageinfo": [{**info, "thumburl": "http://127.0.0.1/private"}]}]
        with patch.object(images, "read_public_resource", return_value=(json.dumps({"query": {"pages": pages}}).encode(), "application/json")):
            results = images.commons_candidates("bridge", 2)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["author"], "Artist")
        self.assertEqual(results[0]["title"], "Bridge.jpg")

    def test_preview_decodes_real_pixels_and_rejects_svg_and_large_payloads(self):
        data, width, height = images.preview_image(png())
        self.assertEqual((width, height), (100, 60))
        self.assertEqual(Image.open(io.BytesIO(data)).format, "WEBP")
        for data in [b"<svg><script>bad</script></svg>", b"x" * (images.MAX_BYTES + 1)]:
            with self.assertRaises(Exception): images.preview_image(data)

    def test_cached_source_reuses_storage_without_downloading(self):
        pool, storage = FakePool(), Mock(expires_in=900)
        pool.conn.fetchrow.return_value = ROW
        storage.sign.return_value = "signed-preview"
        with patch.object(images, "ensure_schema", AsyncMock()), patch.object(images, "get_pool", AsyncMock(return_value=pool)), \
             patch.object(images, "read_public_resource") as download:
            result = asyncio.run(images.store_candidate("user-1", CANDIDATE, storage))
        self.assertEqual(result["url"], "signed-preview")
        self.assertNotIn("object_key", result)
        self.assertNotIn("download_url", result)
        download.assert_not_called()
        storage.upload.assert_not_called()

    def test_failed_database_save_removes_only_this_new_object(self):
        pool, storage = FakePool(), Mock()
        pool.conn.fetchrow.side_effect = [None, RuntimeError("DB down")]
        storage.upload.return_value = "new-key"
        with patch.object(images, "ensure_schema", AsyncMock()), patch.object(images, "get_pool", AsyncMock(return_value=pool)), \
             patch.object(images, "read_public_resource", return_value=(png(), "image/png")):
            with self.assertRaises(RuntimeError): asyncio.run(images.store_candidate("user-1", CANDIDATE, storage))
        storage.delete.assert_called_once_with("new-key")

    def test_failed_signing_does_not_delete_committed_object(self):
        pool, storage = FakePool(), Mock()
        pool.conn.fetchrow.side_effect = [None, ROW]
        storage.upload.return_value = "new-key"
        storage.sign.side_effect = RuntimeError("signing unavailable")
        with patch.object(images, "ensure_schema", AsyncMock()), patch.object(images, "get_pool", AsyncMock(return_value=pool)), \
             patch.object(images, "read_public_resource", return_value=(png(), "image/png")):
            with self.assertRaises(RuntimeError): asyncio.run(images.store_candidate("user-1", CANDIDATE, storage))
        storage.delete.assert_not_called()

    def test_renewal_requires_ownership_and_hides_keys(self):
        with patch.object(image_api, "owned_images", AsyncMock(return_value={})) as owned:
            with self.assertRaises(HTTPException) as failure: asyncio.run(image_api.renew_image(IMAGE_ID, "other-user"))
        self.assertEqual(failure.exception.status_code, 404)
        owned.assert_awaited_once_with("other-user", [IMAGE_ID])
        storage = Mock(expires_in=900)
        storage.sign.return_value = "renewed-url"
        with patch.object(image_api, "owned_images", AsyncMock(return_value={IMAGE_ID: ROW})), \
             patch.object(image_api.R2ImageStorage, "from_env", return_value=storage):
            result = asyncio.run(image_api.renew_image(IMAGE_ID, "user-1"))
        self.assertEqual(result["url"], "renewed-url")
        self.assertNotIn("object_key", result)

    def test_history_saves_only_owned_ids_not_urls_or_client_attribution(self):
        pool = FakePool()
        pool.conn.fetchval.return_value = datetime.now(timezone.utc)
        payload = conversations.ConversationInput(title="Images", messages=[{"id": "m1", "sender": "bot", "content": "",
            "web_images": [{"image_id": IMAGE_ID, "url": "secret-signed-url", "author": "spoofed"}]}])
        with patch.object(conversations, "owned_images", AsyncMock(return_value={IMAGE_ID: ROW})), \
             patch.object(conversations, "ensure_conversation_schema", AsyncMock()), \
             patch.object(conversations, "get_pool", AsyncMock(return_value=pool)):
            asyncio.run(conversations.save_conversation("chat1", payload, "user-1"))
        saved = pool.conn.fetchval.call_args.args[-1]
        self.assertNotIn("secret-signed-url", saved)
        self.assertNotIn("spoofed", saved)
        self.assertEqual(json.loads(saved)[0]["web_images"], [{"image_id": IMAGE_ID}])
        with patch.object(conversations, "owned_images", AsyncMock(return_value={})):
            with self.assertRaises(HTTPException) as failure:
                asyncio.run(conversations.save_conversation("chat1", payload, "other-user"))
        self.assertEqual(failure.exception.status_code, 403)

    def test_history_restores_canonical_metadata_and_fresh_signed_links(self):
        pool, storage = FakePool(), Mock(expires_in=900)
        pool.conn.fetch.side_effect = [[{"id": "chat1", "title": "Images", "updated_at": datetime.now(timezone.utc),
            "deleted_at": None, "messages": [{"id": "m1", "sender": "bot", "content": "Image", "web_images": [{"image_id": IMAGE_ID}]}]}], []]
        storage.sign.return_value = "fresh-url"
        with patch.object(conversations, "ensure_conversation_schema", AsyncMock()), \
             patch.object(conversations, "get_pool", AsyncMock(return_value=pool)), \
             patch.object(conversations, "owned_images", AsyncMock(return_value={IMAGE_ID: ROW})) as owned, \
             patch.object(conversations.R2ImageStorage, "from_env", return_value=storage):
            result = asyncio.run(conversations.list_conversations("user-1"))
        restored = result["conversations"][0]["messages"][0]["web_images"][0]
        self.assertEqual(restored["url"], "fresh-url")
        self.assertEqual(restored["author"], "Test author")
        self.assertEqual(restored["license"], "CC BY-SA 4.0")
        owned.assert_awaited_once_with("user-1", [IMAGE_ID])

    def test_model_selected_tool_has_progress_and_real_attachments(self):
        rounds = iter([[{"functionCall": {"id": "i1", "name": "search_web_images", "args": {"query": "bridge", "limit": 1}}}], [{"text": "The image is shown below."}]])
        async def collect(): return [event async for event in agent.answer_with_tools("user-1", "Show me a bridge photo", "", [], {})]
        with patch.object(agent, "image_search_configured", return_value=True), \
             patch.object(agent, "stream_gemini_parts", side_effect=lambda *a: iter(next(rounds))), \
             patch.object(agent, "search_and_store", AsyncMock(return_value=[{**ROW["metadata"], "image_id": IMAGE_ID,
                        "url": "secret-signed-url", "url_expires_in": 900}])):
            events = asyncio.run(collect())
        statuses = [data["status"] for kind, data in events if kind == "tool_call"]
        self.assertEqual(statuses, ["running", "done"])
        self.assertTrue(any(kind == "web_images" for kind, data in events))
        evidence = [data for kind, data in events if kind == "evidence"]
        self.assertNotIn("secret-signed-url", str(evidence))

    def test_no_result_has_no_attachment_and_no_guessed_url(self):
        with patch.object(images, "configured", return_value=True), patch.object(images.R2ImageStorage, "from_env", return_value=Mock()), \
             patch.object(images, "commons_candidates", return_value=[]):
            self.assertEqual(asyncio.run(images.search_and_store("user-1", "unknown concept", 1)), [])

    def test_owned_query_always_has_account_filter(self):
        pool = FakePool()
        pool.conn.fetch.return_value = []
        with patch.object(images, "ensure_schema", AsyncMock()), patch.object(images, "get_pool", AsyncMock(return_value=pool)):
            self.assertEqual(asyncio.run(images.owned_images("user-1", [IMAGE_ID])), {})
        query, user, ids = pool.conn.fetch.call_args.args
        self.assertIn("user_id=$1", query)
        self.assertEqual(user, "user-1")
        self.assertEqual(ids, [IMAGE_ID])
