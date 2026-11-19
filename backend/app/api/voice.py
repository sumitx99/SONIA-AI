"""Voice mode: realtime voice sessions (Gemini Live), and speech to text for the standard voice
in browsers that can't recognise speech themselves."""

import asyncio
import time
from collections import defaultdict, deque
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from typing import Literal

from pydantic import BaseModel, Field

from app.core.auth import current_user
from app.services import live_voice, speech
from app.services.chat_memory import HistoryTurn
from app.services.images.image_storage import valid_chat_id
from app.services.memory import chat_project

router = APIRouter(prefix="/voice", tags=["Voice"])

MAX_AUDIO_BYTES = 10 * 1024 * 1024  # about ten minutes of compressed speech
MIN_AUDIO_BYTES = 1000
AUDIO_TYPES = ("audio/", "video/webm", "video/mp4")  # some browsers label recordings as video
# Per-user requests per minute.
LIMITS = {"transcribe": 30, "live": 10, "tool": 60}
_recent: dict[tuple[str, str], deque] = defaultdict(deque)


def _rate_limit(user_id: str, action: str):
    window, now = _recent[(user_id, action)], time.monotonic()
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= LIMITS[action]:
        raise HTTPException(429, "Voice mode is busy. Please wait a moment and try again.")
    window.append(now)


@router.get("/status")
async def status(_user_id: str = Depends(current_user)):
    """Whether this server can transcribe speech, so the app only offers what works."""
    return {"transcription": speech.transcription_configured()}


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), user_id: str = Depends(current_user)):
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if not content_type.startswith(AUDIO_TYPES):
        raise HTTPException(415, "Send a recording in a common audio format.")
    audio = await file.read(MAX_AUDIO_BYTES + 1)
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "That recording is too long. Keep each turn under a few minutes.")
    if len(audio) < MIN_AUDIO_BYTES:
        return {"text": ""}
    _rate_limit(user_id, "transcribe")
    extension = {"audio/mp4": "m4a", "video/mp4": "mp4", "audio/ogg": "ogg", "audio/wav": "wav",
                 "audio/mpeg": "mp3"}.get(content_type, "webm")
    try:
        text = await asyncio.to_thread(speech.transcribe, audio, f"speech.{extension}", content_type)
    except speech.SpeechUnavailable as error:
        raise HTTPException(503, str(error))
    return {"text": text}


class LiveStart(BaseModel):
    voice: Literal["male", "female"] = "female"
    chat_id: str | None = Field(None, max_length=64)
    project_id: str | None = Field(None, max_length=64)
    document_ids: list[int] = Field(default_factory=list, max_length=200)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=40)


@router.post("/live")
async def start_live(payload: LiveStart, user_id: str = Depends(current_user)):
    """A token for one realtime voice session, with Sonia's setup locked in."""
    if not valid_chat_id(payload.chat_id) or not valid_chat_id(payload.project_id):
        raise HTTPException(422, "Invalid conversation or project ID")
    _rate_limit(user_id, "live")
    project = await chat_project(user_id, payload.chat_id, payload.project_id)
    try:
        return await live_voice.start_session(user_id, payload.voice, payload.chat_id, project,
                                              payload.document_ids, [turn.model_dump() for turn in payload.history])
    except live_voice.LiveUnavailable as error:
        raise HTTPException(503, str(error))


class LiveToolCall(BaseModel):
    session_id: str = Field(max_length=64)
    name: str = Field(max_length=100)
    args: dict = Field(default_factory=dict)


@router.post("/live/tool")
async def live_tool(payload: LiveToolCall, user_id: str = Depends(current_user)):
    """Runs a tool the realtime model asked for, within what its session allows."""
    _rate_limit(user_id, "tool")
    try:
        return {"result": await live_voice.run_tool(user_id, payload.session_id, payload.name, payload.args)}
    except PermissionError as error:
        raise HTTPException(403, str(error))
