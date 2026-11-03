"""Account-owned chat history. Signed R2 URLs are renewed, never persisted."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import current_user
from app.db import ensure_document_schema, get_pool, owned_document_ids
from app.image_storage import valid_chat_id

router = APIRouter(prefix="/conversations", tags=["Conversations"])
_schema_ready = False


async def ensure_conversation_schema():
    global _schema_ready
    if _schema_ready:
        return
    await ensure_document_schema()
    async with (await get_pool()).acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                user_id TEXT NOT NULL,
                id TEXT NOT NULL,
                title TEXT NOT NULL,
                messages JSONB NOT NULL DEFAULT '[]'::jsonb,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                deleted_at TIMESTAMPTZ,
                PRIMARY KEY (user_id, id)
            );
            ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
        """)
    _schema_ready = True


class SavedImage(BaseModel):
    image_id: str = Field(max_length=100)
    document_id: int
    image_number: int
    page_number: int
    heading_path: list[str] = Field(default_factory=list, max_length=10)
    caption: str | None = Field(None, max_length=1000)
    width: int = 0
    height: int = 0
    source_path: str = Field("", max_length=300)
    url_expires_in: int = 900


class SavedMessage(BaseModel):
    id: str = Field(max_length=100)
    content: str = Field(max_length=100_000)
    sender: Literal["user", "bot"]
    error: bool = False
    notice: str | None = Field(None, max_length=2000)
    images: list[SavedImage] = Field(default_factory=list, max_length=25)


class ConversationInput(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    messages: list[SavedMessage] = Field(default_factory=list, max_length=1000)


@router.get("")
async def list_conversations(user_id: str = Depends(current_user)):
    await ensure_conversation_schema()
    async with (await get_pool()).acquire() as conn:
        saved = await conn.fetch(
            "SELECT id, title, messages, updated_at, deleted_at FROM conversations "
            "WHERE user_id = $1 ORDER BY updated_at DESC", user_id)
        documents = await conn.fetch("""
            SELECT id, filename, chat_id, uploaded_at FROM documents d
            WHERE user_id = $1 AND EXISTS
                (SELECT 1 FROM document_chunks c WHERE c.document_id = d.id)
            ORDER BY uploaded_at DESC
        """, user_id)
    hidden = {row["id"] for row in saved if row["deleted_at"] is not None}
    history = {}
    for row in saved:
        if row["id"] in hidden:
            continue
        messages = row["messages"]
        if isinstance(messages, str):
            messages = json.loads(messages)
        # Persisted messages contain image references. The UI renews their URLs on display.
        for message in messages:
            for image in message.get("images", []):
                image["url"] = ""
        history[row["id"]] = {"id": row["id"], "title": row["title"], "messages": messages,
                              "documents": [], "documentIds": [],
                              "updatedAt": row["updated_at"].isoformat(), "recovered": False}
    for document in documents:
        chat_id = document["chat_id"] or f"document-{document['id']}"
        if chat_id in hidden:
            continue
        if chat_id not in history:
            history[chat_id] = {"id": chat_id, "title": document["filename"], "messages": [],
                                "documents": [], "documentIds": [], "recovered": True,
                                "updatedAt": document["uploaded_at"].isoformat()}
        history[chat_id]["documents"].append(document["filename"])
        history[chat_id]["documentIds"].append(document["id"])
    return {"conversations": sorted(history.values(), key=lambda item: item["updatedAt"], reverse=True)}


@router.put("/{chat_id}")
async def save_conversation(chat_id: str, payload: ConversationInput, user_id: str = Depends(current_user)):
    if not valid_chat_id(chat_id):
        raise HTTPException(422, "Invalid conversation ID")
    image_documents = {image.document_id for message in payload.messages for image in message.images}
    if image_documents and set(await owned_document_ids(user_id, list(image_documents))) != image_documents:
        raise HTTPException(403, "An image belongs to a document outside your account")
    messages = json.dumps([message.model_dump(exclude_none=True) for message in payload.messages])
    if len(messages.encode()) > 2_000_000:
        raise HTTPException(413, "This conversation is too large. Start a new conversation.")
    await ensure_conversation_schema()
    async with (await get_pool()).acquire() as conn:
        # Soft-deleted chats cannot be resurrected by a delayed auto-save.
        updated = await conn.fetchval("""
            INSERT INTO conversations(user_id, id, title, messages)
            VALUES ($1, $2, $3, $4::jsonb)
            ON CONFLICT(user_id, id) DO UPDATE
                SET title = EXCLUDED.title, messages = EXCLUDED.messages, updated_at = now()
                WHERE conversations.deleted_at IS NULL
            RETURNING updated_at
        """, user_id, chat_id, payload.title, messages)
    if updated is None:
        raise HTTPException(409, "This conversation was deleted")
    return {"updatedAt": updated.isoformat()}


@router.delete("/{chat_id}")
async def delete_conversation(chat_id: str, user_id: str = Depends(current_user)):
    if not valid_chat_id(chat_id):
        raise HTTPException(422, "Invalid conversation ID")
    await ensure_conversation_schema()
    async with (await get_pool()).acquire() as conn:
        await conn.execute("""
            INSERT INTO conversations(user_id, id, title, deleted_at)
            VALUES ($1, $2, 'Deleted conversation', now())
            ON CONFLICT(user_id, id) DO UPDATE SET deleted_at = now(), updated_at = now()
        """, user_id, chat_id)
    return {"deleted": True}
