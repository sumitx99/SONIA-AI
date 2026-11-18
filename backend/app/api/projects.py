"""Projects: named groups of chats with shared instructions, files and a fixed memory mode.

Memory mode is chosen once, when the project is created:
  default       chats in the project share the account's memory and past-chat search.
  project_only  the project's chats only see its own memory and chats, and nothing outside
                the project sees them.
"""

import asyncio
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.conversations import ensure_conversation_schema
from app.core.auth import current_user
from app.core.db import get_pool
from app.services.conversation_cache import invalidate_conversations
from app.services.images.image_storage import R2ImageStorage, document_prefix, valid_chat_id

router = APIRouter(prefix="/projects", tags=["Projects"])
logger = logging.getLogger(__name__)
MAX_PROJECTS = 100
_schema_ready = False

MemoryMode = Literal["default", "project_only"]


async def ensure_project_schema():
    global _schema_ready
    if _schema_ready:
        return
    await ensure_conversation_schema()
    async with (await get_pool()).acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                user_id TEXT NOT NULL,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                instructions TEXT NOT NULL DEFAULT '',
                memory_mode TEXT NOT NULL DEFAULT 'default'
                    CHECK (memory_mode IN ('default', 'project_only')),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                deleted_at TIMESTAMPTZ,
                PRIMARY KEY (user_id, id)
            );
            ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
        """)
    _schema_ready = True


async def get_project(user_id: str, project_id: str | None) -> dict | None:
    """The user's live project, or None (also for another account's or a deleted project)."""
    if not project_id or not valid_chat_id(project_id):
        return None
    await ensure_project_schema()
    async with (await get_pool()).acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, instructions, memory_mode FROM projects "
            "WHERE user_id = $1 AND id = $2 AND deleted_at IS NULL", user_id, project_id)
    return dict(row) if row else None


async def project_document_ids(user_id: str, project_id: str) -> list[int]:
    async with (await get_pool()).acquire() as conn:
        rows = await conn.fetch(
            "SELECT d.id FROM documents d WHERE d.user_id = $1 AND d.project_id = $2 AND EXISTS "
            "(SELECT 1 FROM document_chunks c WHERE c.document_id = d.id) ORDER BY d.id",
            user_id, project_id)
    return [row["id"] for row in rows]


def _project_json(row, documents) -> dict:
    return {"id": row["id"], "name": row["name"], "instructions": row["instructions"],
            "memoryMode": row["memory_mode"], "createdAt": row["created_at"].isoformat(),
            "updatedAt": row["updated_at"].isoformat(), "documents": documents}


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    memory_mode: MemoryMode = "default"


class ProjectUpdate(BaseModel):
    # The memory mode is deliberately not editable: changing it later would mix memories
    # that were promised to stay apart.
    name: str | None = Field(None, min_length=1, max_length=100)
    instructions: str | None = Field(None, max_length=8000)


@router.get("")
async def list_projects(user_id: str = Depends(current_user)):
    await ensure_project_schema()
    async with (await get_pool()).acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, instructions, memory_mode, created_at, updated_at FROM projects "
            "WHERE user_id = $1 AND deleted_at IS NULL ORDER BY updated_at DESC", user_id)
        documents = await conn.fetch(
            "SELECT d.id, d.filename, d.project_id FROM documents d WHERE d.user_id = $1 "
            "AND d.project_id IS NOT NULL AND EXISTS "
            "(SELECT 1 FROM document_chunks c WHERE c.document_id = d.id) ORDER BY d.uploaded_at", user_id)
    files: dict[str, list] = {}
    for document in documents:
        files.setdefault(document["project_id"], []).append(
            {"id": document["id"], "filename": document["filename"]})
    return {"projects": [_project_json(row, files.get(row["id"], [])) for row in rows]}


@router.post("")
async def create_project(payload: ProjectCreate, user_id: str = Depends(current_user)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Give the project a name.")
    await ensure_project_schema()
    async with (await get_pool()).acquire() as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM projects WHERE user_id = $1 AND deleted_at IS NULL", user_id)
        if count >= MAX_PROJECTS:
            raise HTTPException(409, f"You can have up to {MAX_PROJECTS} projects.")
        row = await conn.fetchrow(
            "INSERT INTO projects (user_id, id, name, memory_mode) VALUES ($1, $2, $3, $4) "
            "RETURNING id, name, instructions, memory_mode, created_at, updated_at",
            user_id, str(uuid.uuid4()), name, payload.memory_mode)
    return _project_json(row, [])


@router.patch("/{project_id}")
async def update_project(project_id: str, payload: ProjectUpdate, user_id: str = Depends(current_user)):
    if not await get_project(user_id, project_id):
        raise HTTPException(404, "Project not found")
    name = payload.name.strip() if payload.name is not None else None
    if name == "":
        raise HTTPException(422, "Give the project a name.")
    async with (await get_pool()).acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE projects SET name = COALESCE($3, name), instructions = COALESCE($4, instructions), "
            "updated_at = now() WHERE user_id = $1 AND id = $2 AND deleted_at IS NULL "
            "RETURNING id, name, instructions, memory_mode, created_at, updated_at",
            user_id, project_id, name, payload.instructions)
    documents = [{"id": item, "filename": filename}
                 for item, filename in await _project_files(user_id, project_id, ready_only=True)]
    return _project_json(row, documents)


async def _project_files(user_id, project_id, ready_only=False):
    ready = (" AND EXISTS (SELECT 1 FROM document_chunks c WHERE c.document_id = documents.id)"
             if ready_only else "")
    async with (await get_pool()).acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, filename FROM documents WHERE user_id = $1 AND project_id = $2"
            f"{ready} ORDER BY uploaded_at", user_id, project_id)
    return [(row["id"], row["filename"]) for row in rows]


@router.delete("/{project_id}")
async def delete_project(project_id: str, user_id: str = Depends(current_user)):
    """Deletes the project with its chats, files and project memory."""
    if not await get_project(user_id, project_id):
        raise HTTPException(404, "Project not found")
    files = await _project_files(user_id, project_id)
    async with (await get_pool()).acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE projects SET deleted_at = now(), updated_at = now() WHERE user_id = $1 AND id = $2",
                user_id, project_id)
            await conn.execute(
                "UPDATE conversations SET deleted_at = now(), updated_at = now() "
                "WHERE user_id = $1 AND project_id = $2 AND deleted_at IS NULL", user_id, project_id)
            await conn.execute("DELETE FROM documents WHERE user_id = $1 AND project_id = $2",
                               user_id, project_id)
    # Imported lazily: memory depends on projects, not the other way round.
    from app.services.memory import forget_scope
    await forget_scope(user_id, project_id)
    await _remove_stored_files(user_id, [item for item, _ in files])
    await invalidate_conversations(user_id)
    return {"deleted": True}


@router.delete("/{project_id}/documents/{document_id}")
async def delete_project_document(project_id: str, document_id: int, user_id: str = Depends(current_user)):
    if not await get_project(user_id, project_id):
        raise HTTPException(404, "Project not found")
    async with (await get_pool()).acquire() as conn:
        deleted = await conn.fetchval(
            "DELETE FROM documents WHERE id = $1 AND user_id = $2 AND project_id = $3 RETURNING id",
            document_id, user_id, project_id)
    if deleted is None:
        raise HTTPException(404, "File not found")
    await _remove_stored_files(user_id, [document_id])
    return {"deleted": True}


async def _remove_stored_files(user_id, document_ids):
    try:
        storage = R2ImageStorage.from_env()
    except ValueError:
        storage = None
    if not storage:
        return
    for document_id in document_ids:
        try:
            # Project files are stored without a chat, under the unassigned prefix.
            await asyncio.to_thread(storage.delete_upload, document_prefix(user_id, None, document_id))
        except Exception:
            logger.warning("Could not remove the stored files of document %s", document_id)
