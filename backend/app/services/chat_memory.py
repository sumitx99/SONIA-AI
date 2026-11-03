"""Bounded conversational text, separate from document retrieval and tool instructions."""
import json
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

MAX_MESSAGES = 20
MAX_CHARACTERS = 24000

class HistoryTurn(BaseModel):
    sender: Literal['user', 'bot']
    content: str = Field(max_length=12000)


def parse_history(raw: str | None) -> list[dict]:
    if not raw:
        return []
    if len(raw) > 100000:
        raise HTTPException(413, 'Conversation context is too large.')
    try:
        items = json.loads(raw)
        if not isinstance(items, list) or len(items) > 50:
            raise ValueError('Expected a list of up to 50 messages')
        validated = [HistoryTurn.model_validate(item).model_dump() for item in items]
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(422, 'Invalid conversation context.')
    result, remaining = [], MAX_CHARACTERS
    for item in reversed(validated[-MAX_MESSAGES:]):
        text = item['content'].strip()
        if not text:
            continue
        if len(text) > remaining:
            break
        result.append({**item, 'content': text})
        remaining -= len(text)
    result.reverse()
    while result and result[0]["sender"] != "user":
        result.pop(0)
    return result
