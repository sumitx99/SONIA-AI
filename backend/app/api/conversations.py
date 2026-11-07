"""Account-owned chat history. Signed R2 URLs are renewed, never persisted."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import current_user
from app.core.db import ensure_document_schema, get_pool, owned_document_ids
from app.services.images.image_storage import valid_chat_id
from app.services.images.web_images import owned_images, attachment as web_attachment
from app.services.images.image_storage import R2ImageStorage

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


class SavedToolCall(BaseModel):
    """A tool Sonia used for an answer, as shown in chat (arguments aren't kept)."""
    id: str = Field(max_length=100)
    server: str = Field(max_length=100)
    tool: str = Field(max_length=200)
    title: str = Field("", max_length=200)
    status: Literal["awaiting_approval", "running", "done", "error", "denied", "stopped"]
    summary: str | None = Field(None, max_length=500)


class SavedSource(BaseModel):
    """A web page Sonia read for an answer."""
    title: str = Field("", max_length=200)
    url: str = Field(max_length=2048, pattern=r"^https?://")


class SavedWebImage(BaseModel):
    # Canonical source/license metadata stays server-owned. Never persist signed URLs.
    image_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class SavedCitation(BaseModel):
    """One numbered citation in an answer, as checked against its source."""
    n: int = Field(ge=1, le=99)
    kind: Literal["document", "web", "tool", "unknown"]
    title: str = Field("", max_length=300)
    quote: str = Field("", max_length=1000)
    verified: bool = False
    # The source exists but its text could not be read, so the quote was never checked.
    source_unreadable: bool = False
    url: str | None = Field(None, max_length=2048, pattern=r"^https?://")
    document_id: int | None = None
    chunk_id: int | None = None


class SavedMessage(BaseModel):
    id: str = Field(max_length=100)
    content: str = Field(max_length=100_000)
    sender: Literal["user", "bot"]
    error: bool = False
    notice: str | None = Field(None, max_length=2000)
    images: list[SavedImage] = Field(default_factory=list, max_length=25)
    web_images: list[SavedWebImage] = Field(default_factory=list, max_length=6)
    tool_calls: list[SavedToolCall] = Field(default_factory=list, max_length=30)
    sources: list[SavedSource] = Field(default_factory=list, max_length=10)
    citations: list[SavedCitation] = Field(default_factory=list, max_length=40)
    # Set on an upload's "ready" message while that document's images are still being processed,
    # so the chat can resume checking their status after a reload.
    images_pending_document_id: int | None = None


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
    refs = [image["image_id"] for chat in history.values() for message in chat["messages"] for image in message.get("web_images", [])]
    if refs:
        rows = await owned_images(user_id, refs)
        try:
            storage = R2ImageStorage.from_env()
        except ValueError:
            storage = None  # Preserve saved references even while storage configuration is unavailable.
        for chat in history.values():
            for message in chat["messages"]:
                message["web_images"] = [web_attachment(rows[image["image_id"]], storage)
                    for image in message.get("web_images", []) if image["image_id"] in rows]
    return {"conversations": sorted(history.values(), key=lambda item: item["updatedAt"], reverse=True)}


@router.put("/{chat_id}")
async def save_conversation(chat_id: str, payload: ConversationInput, user_id: str = Depends(current_user)):
    if not valid_chat_id(chat_id):
        raise HTTPException(422, "Invalid conversation ID")
    image_documents = {image.document_id for message in payload.messages for image in message.images}
    image_documents |= {message.images_pending_document_id for message in payload.messages
                        if message.images_pending_document_id is not None}
    if image_documents and set(await owned_document_ids(user_id, list(image_documents))) != image_documents:
        raise HTTPException(403, "An image belongs to a document outside your account")
    web_refs = {image.image_id for message in payload.messages for image in message.web_images}
    if web_refs and set(await owned_images(user_id, web_refs)) != web_refs:
        raise HTTPException(403, "A web image does not belong to your account")
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
