"""Memory settings: see what Sonia remembers, add or remove items, rebuild or reset it."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.projects import get_project
from app.core.auth import current_user
from app.services import memory

router = APIRouter(prefix="/memory", tags=["Memory"])
_refreshing: set[tuple[str, str]] = set()


async def _scope(user_id: str, project_id: str | None) -> str:
    """Global memory, or the separate memory of a project-only project."""
    if not project_id:
        return memory.GLOBAL
    project = await get_project(user_id, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if project["memory_mode"] != "project_only":
        raise HTTPException(422, "This project shares your account memory.")
    return memory.scope_for(project)


class MemorySettings(BaseModel):
    enabled: bool


class MemoryItem(BaseModel):
    action: Literal["remember", "forget"] = "remember"
    content: str = Field(min_length=1, max_length=memory.MAX_EDIT_CHARS)


@router.get("")
async def get_memory(project_id: str | None = Query(None), user_id: str = Depends(current_user)):
    return await memory.memory_overview(user_id, await _scope(user_id, project_id))


@router.put("/settings")
async def update_settings(payload: MemorySettings, user_id: str = Depends(current_user)):
    await memory.set_memory_enabled(user_id, payload.enabled)
    return {"enabled": payload.enabled}


@router.post("/edits")
async def add_item(payload: MemoryItem, project_id: str | None = Query(None), user_id: str = Depends(current_user)):
    try:
        return await memory.add_edit(user_id, await _scope(user_id, project_id), payload.action, payload.content)
    except ValueError as error:
        raise HTTPException(422, str(error))


@router.delete("/edits/{edit_id}")
async def delete_item(edit_id: int, project_id: str | None = Query(None), user_id: str = Depends(current_user)):
    if not await memory.delete_edit(user_id, await _scope(user_id, project_id), edit_id):
        raise HTTPException(404, "Memory item not found")
    return {"deleted": True}


@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: int, project_id: str | None = Query(None), user_id: str = Depends(current_user)):
    if not await memory.delete_entry(user_id, await _scope(user_id, project_id), entry_id):
        raise HTTPException(404, "Memory entry not found")
    return {"deleted": True}


@router.post("/refresh")
async def refresh(project_id: str | None = Query(None), user_id: str = Depends(current_user)):
    """Rebuilds the summary now (one model call), instead of waiting for the next chat."""
    scope = await _scope(user_id, project_id)
    if not await memory.memory_enabled(user_id):
        raise HTTPException(409, "Turn memory on first.")
    if (user_id, scope) in _refreshing:
        raise HTTPException(409, "Memory is already being updated.")
    _refreshing.add((user_id, scope))
    try:
        await memory.refresh_summary(user_id, scope)
    except Exception:
        raise HTTPException(503, "Memory could not be updated right now. Please try again later.")
    finally:
        _refreshing.discard((user_id, scope))
    return await memory.memory_overview(user_id, scope)


@router.delete("")
async def reset(project_id: str | None = Query(None), user_id: str = Depends(current_user)):
    scope = await _scope(user_id, project_id)
    await memory.reset_memory(user_id, scope)
    return await memory.memory_overview(user_id, scope)
