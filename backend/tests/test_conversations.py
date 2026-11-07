import asyncio
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.api.conversations import (ConversationInput, SavedImage, delete_conversation,
                               list_conversations, save_conversation)
from test_image_pipeline import FakePool


class ConversationTests(unittest.TestCase):
    def test_stopped_tool_activity_survives_saved_message_validation(self):
        chat = ConversationInput(title="Stopped answer", messages=[{
            "id": "answer-1", "sender": "bot", "content": "Partial answer",
            "tool_calls": [{"id": "jobs-1", "server": "JSearch Jobs", "tool": "Job_Search",
                            "title": "Job search", "status": "stopped"}],
        }])
        self.assertEqual(chat.model_dump()["messages"][0]["tool_calls"][0]["status"], "stopped")

    def setUp(self):
        self.pool = FakePool()
        self.schema = patch("app.api.conversations.ensure_conversation_schema", AsyncMock())
        self.pool_patch = patch("app.api.conversations.get_pool", AsyncMock(return_value=self.pool))
        self.schema.start()
        self.pool_patch.start()
        self.addCleanup(self.schema.stop)
        self.addCleanup(self.pool_patch.stop)
        self.now = datetime.now(timezone.utc)

    def test_saved_history_and_previously_uploaded_documents_are_account_scoped(self):
        self.pool.conn.fetch.side_effect = [[
            {"id": "chat-1", "title": "Saved conversation", "messages": json.dumps([
                {"id": "m1", "sender": "bot", "content": "Saved answer", "images": [{"image_id": "i1"}]}]),
             "updated_at": self.now, "deleted_at": None},
            {"id": "hidden", "title": "Deleted", "messages": "[]", "updated_at": self.now, "deleted_at": self.now},
        ], [
            {"id": 7, "filename": "saved.pdf", "chat_id": "chat-1", "uploaded_at": self.now},
            {"id": 8, "filename": "earlier.pdf", "chat_id": "old-chat", "uploaded_at": self.now},
            {"id": 9, "filename": "hidden.pdf", "chat_id": "hidden", "uploaded_at": self.now},
        ]]
        result = asyncio.run(list_conversations("user-1"))["conversations"]
        chats = {chat["id"]: chat for chat in result}
        self.assertEqual(set(chats), {"chat-1", "old-chat"})
        self.assertEqual(chats["chat-1"]["messages"][0]["content"], "Saved answer")
        self.assertEqual(chats["chat-1"]["messages"][0]["images"][0]["url"], "")
        self.assertEqual(chats["chat-1"]["documentIds"], [7])
        self.assertTrue(chats["old-chat"]["recovered"])
        self.assertEqual(chats["old-chat"]["messages"], [])
        for call in self.pool.conn.fetch.call_args_list:
            self.assertIn("user_id = $1", call.args[0])
            self.assertEqual(call.args[1], "user-1")

    def test_saving_excludes_presigned_urls_and_uses_verified_owner(self):
        self.pool.conn.fetchval.return_value = self.now
        payload = ConversationInput(title="Saved", messages=[{
            "id": "m1", "sender": "bot", "content": "Answer", "images": [{
                "image_id": "i1", "document_id": 7, "image_number": 1, "page_number": 2,
                "url": "https://private.example/?signature=secret", "source_url": "signed-pdf",
            }],
        }])
        with patch("app.api.conversations.owned_document_ids", AsyncMock(return_value=[7])):
            asyncio.run(save_conversation("chat-1", payload, "user-1"))
        sql, user, chat_id, title, messages = self.pool.conn.fetchval.call_args.args
        self.assertEqual((user, chat_id, title), ("user-1", "chat-1", "Saved"))
        self.assertNotIn("signature", messages)
        self.assertNotIn("source_url", messages)
        self.assertIn("ON CONFLICT(user_id, id)", sql)
        self.assertIn("WHERE conversations.deleted_at IS NULL", sql)

    def test_images_from_other_accounts_cannot_be_persisted(self):
        payload = ConversationInput(title="Not mine", messages=[{
            "id": "m1", "sender": "bot", "content": "", "images": [{
                "image_id": "other", "document_id": 999, "image_number": 1, "page_number": 1,
            }],
        }])
        with patch("app.api.conversations.owned_document_ids", AsyncMock(return_value=[])):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(save_conversation("chat-1", payload, "user-1"))
        self.assertEqual(error.exception.status_code, 403)
        self.pool.conn.fetchval.assert_not_called()

    def test_pending_image_marker_is_saved_for_an_owned_document_only(self):
        self.pool.conn.fetchval.return_value = self.now
        message = {"id": "m1", "sender": "bot", "content": "Ready", "images_pending_document_id": 7}
        with patch("app.api.conversations.owned_document_ids", AsyncMock(return_value=[7])) as owned:
            asyncio.run(save_conversation("chat-1", ConversationInput(title="Saved", messages=[message]), "user-1"))
        owned.assert_awaited_once_with("user-1", [7])
        saved = json.loads(self.pool.conn.fetchval.call_args.args[4])
        self.assertEqual(saved[0]["images_pending_document_id"], 7)
        self.pool.conn.fetchval.reset_mock()
        with patch("app.api.conversations.owned_document_ids", AsyncMock(return_value=[])):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(save_conversation("chat-1", ConversationInput(
                    title="Not mine", messages=[{**message, "images_pending_document_id": 999}]), "user-1"))
        self.assertEqual(error.exception.status_code, 403)
        self.pool.conn.fetchval.assert_not_called()

    def test_deleted_chat_rejects_late_autosave(self):
        self.pool.conn.fetchval.return_value = None
        with self.assertRaises(HTTPException) as error:
            asyncio.run(save_conversation("chat-1", ConversationInput(title="Old snapshot"), "user-1"))
        self.assertEqual(error.exception.status_code, 409)

    def test_delete_is_recoverable_and_scoped_to_account(self):
        asyncio.run(delete_conversation("chat-1", "user-1"))
        sql, owner, chat = self.pool.conn.execute.call_args.args
        self.assertIn("deleted_at", sql)
        self.assertNotIn("DELETE FROM", sql)
        self.assertEqual((owner, chat), ("user-1", "chat-1"))
