"""/mcp-connections: the remote MCP servers a user lets Sonia use in chat."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import current_user
from app.mcp_client import store
from app.mcp_client.safety import UnsafeURLError
from app.mcp_client.session import fetch_tools

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mcp-connections", tags=["MCP connections"])


class ConnectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    url: str = Field(min_length=8, max_length=2048)
    auth_type: Literal["none", "header"] = "none"
    header_name: str = Field("Authorization", max_length=100, pattern=r"^[A-Za-z0-9-]+$")
    header_value: str = Field("", max_length=4096)


class ConnectionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=60)
    enabled: bool | None = None
    tool_policies: dict[str, Literal["allow", "ask", "off"]] | None = None


async def _tools_or_400(connection: dict) -> list[dict]:
    try:
        return await fetch_tools(connection)
    except UnsafeURLError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        logger.info("MCP server %s unreachable: %r", connection["url"], error)
        raise HTTPException(status_code=400, detail=(
            "Couldn't connect to that MCP server. Check the URL and credentials, "
            "and that it supports Streamable HTTP."))


def _public(connection: dict) -> dict:
    return {key: value for key, value in connection.items() if key != "secret"}


@router.get("")
async def list_mcp_connections(user_id: str = Depends(current_user)):
    return {"connections": [_public(c) for c in await store.list_connections(user_id)]}


@router.post("", status_code=201)
async def add_mcp_connection(payload: ConnectionInput, user_id: str = Depends(current_user)):
    if await store.count_connections(user_id) >= store.MAX_CONNECTIONS:
        raise HTTPException(status_code=400, detail=f"You can add up to {store.MAX_CONNECTIONS} connections.")
    if payload.auth_type == "header" and not payload.header_value.strip():
        raise HTTPException(status_code=422, detail="Enter the header value (for example your API key).")
    secret = ({"header_name": payload.header_name, "header_value": payload.header_value.strip()}
              if payload.auth_type == "header" else None)
    if secret:
        try:
            store.encrypt_secret(secret)
        except store.SecretKeyMissing as error:
            raise HTTPException(status_code=503, detail=str(error))
    candidate = {"url": payload.url.strip(), "auth_type": payload.auth_type, "secret": secret}
    tools = await _tools_or_400(candidate)
    return await store.create_connection(user_id, payload.name.strip(), candidate["url"],
                                         payload.auth_type, secret, tools)


@router.post("/{connection_id}/refresh")
async def refresh_mcp_connection(connection_id: str, user_id: str = Depends(current_user)):
    connection = await store.get_connection(user_id, connection_id, with_secret=True)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        tools = await _tools_or_400(connection)
    except HTTPException as error:
        await store.update_connection(user_id, connection_id, last_error=error.detail)
        raise
    return await store.update_connection(user_id, connection_id, tools=tools, last_error=None)


@router.patch("/{connection_id}")
async def update_mcp_connection(connection_id: str, payload: ConnectionUpdate, user_id: str = Depends(current_user)):
    connection = await store.get_connection(user_id, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    policies = None
    if payload.tool_policies is not None:
        known = {tool["name"]: tool["policy"] for tool in connection["tools"]}
        unknown = set(payload.tool_policies) - set(known)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown tool: {sorted(unknown)[0]}")
        policies = {**known, **payload.tool_policies}
    return await store.update_connection(user_id, connection_id, name=payload.name,
                                         enabled=payload.enabled, tool_policies=policies)


@router.delete("/{connection_id}", status_code=204)
async def delete_mcp_connection(connection_id: str, user_id: str = Depends(current_user)):
    if not await store.delete_connection(user_id, connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
