"""/mcp-connections: the remote MCP servers a user lets Sonia use in chat."""

import html
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.core.auth import current_user
from app.mcp_client import store
from app.mcp_client import oauth
from app.mcp_client.safety import UnsafeURLError, assert_public_url
from app.mcp_client.session import fetch_tools

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mcp-connections", tags=["MCP connections"])


class ConnectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    url: str = Field(min_length=8, max_length=2048)
    auth_type: Literal["none", "header"] = "none"
    headers: list["ConnectionHeader"] = Field(default_factory=list, max_length=10)
    # Kept for clients saved before multiple headers were supported.
    header_name: str = Field("Authorization", max_length=100, pattern=r"^[A-Za-z0-9-]+$")
    header_value: str = Field("", max_length=4096)


class ConnectionHeader(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9-]+$")
    value: str = Field(min_length=1, max_length=4096)


class ConnectionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=60)
    enabled: bool | None = None
    tool_policies: dict[str, Literal["allow", "ask", "off"]] | None = None


class OAuthStart(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    url: str = Field(min_length=8, max_length=2048)


async def _tools_or_400(connection: dict, user_id: str | None = None) -> tuple[list[dict], str | None]:
    try:
        auth = oauth.provider_for(user_id, connection) if connection["auth_type"] == "oauth" else None
        return await fetch_tools(connection, auth, include_server_info=True)
    except UnsafeURLError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        if oauth.needs_reauthorization(error):
            raise HTTPException(status_code=409, detail="Sign in to this server again from Settings → Connections. The OAuth session needs reauthorization.") from None
        logger.info("MCP server %s unreachable: %r", connection["url"], error)
        raise HTTPException(status_code=400, detail=(
            "Couldn't connect to that MCP server. Check the URL and credentials, and that it "
            "supports Streamable HTTP. If it asks you to sign in, choose “Sign in with the service”."))


def _public(connection: dict) -> dict:
    return {key: value for key, value in connection.items() if key != "secret"}


@router.get("")
async def list_mcp_connections(user_id: str = Depends(current_user)):
    return {"connections": [_public(c) for c in await store.list_connections(user_id)]}


@router.post("", status_code=201)
async def add_mcp_connection(payload: ConnectionInput, user_id: str = Depends(current_user)):
    if await store.count_connections(user_id) >= store.MAX_CONNECTIONS:
        raise HTTPException(status_code=400, detail=f"You can add up to {store.MAX_CONNECTIONS} connections.")
    secret = None
    if payload.auth_type == "header":
        raw_headers = payload.headers or [ConnectionHeader(name=payload.header_name, value=payload.header_value)]
        headers: dict[str, str] = {}
        for header in raw_headers:
            name, value = header.name.strip(), header.value.strip()
            if not value:
                raise HTTPException(status_code=422, detail="Enter a value for every header.")
            normalized = name.lower()
            if normalized in {key.lower() for key in headers}:
                raise HTTPException(status_code=422, detail=f"Header {name} was entered more than once.")
            headers[name] = value
        secret = {"headers": headers}
    if secret:
        try:
            store.encrypt_secret(secret)
        except store.SecretKeyMissing as error:
            raise HTTPException(status_code=503, detail=str(error))
    candidate = {"url": payload.url.strip(), "auth_type": payload.auth_type, "secret": secret}
    tools, icon_url = await _tools_or_400(candidate)
    return await store.create_connection(user_id, payload.name.strip(), candidate["url"],
                                         payload.auth_type, secret, tools, icon_url)


@router.post("/oauth/start")
async def start_oauth_connection(payload: OAuthStart, user_id: str = Depends(current_user)):
    """Starts signing in to an MCP server; the browser opens `authorization_url`."""
    if await store.count_connections(user_id) >= store.MAX_CONNECTIONS:
        raise HTTPException(status_code=400, detail=f"You can add up to {store.MAX_CONNECTIONS} connections.")
    try:
        url = await assert_public_url(payload.url)
        store.encrypt_secret({"check": True})
    except UnsafeURLError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except store.SecretKeyMissing as error:
        raise HTTPException(status_code=503, detail=str(error))
    try:
        flow_id, authorization_url = await oauth.start_flow(user_id, payload.name.strip(), url)
    except Exception as error:
        logger.info("Couldn't start OAuth for %s: %r", url, error)
        raise HTTPException(status_code=400, detail=(
            "That server didn't offer an OAuth sign-in. Try connecting it with an API key instead."))
    return {"flow_id": flow_id, "authorization_url": authorization_url}


@router.get("/oauth/status/{flow_id}")
async def oauth_connection_status(flow_id: str, user_id: str = Depends(current_user)):
    status = oauth.flow_status(user_id, flow_id)
    if status is None:
        raise HTTPException(status_code=404, detail="This sign-in has expired. Please start again.")
    return status


@router.get(oauth.CALLBACK_PATH.removeprefix("/mcp-connections"), response_class=HTMLResponse,
            include_in_schema=False)
async def oauth_connection_callback(state: str = "", code: str | None = None, error: str | None = None,
                                    iss: str | None = None):
    """Where the MCP server's sign-in sends the browser back. No Sonia login: `state` binds it."""
    flow = oauth.finish_flow(state, code, error, iss)
    if flow is None:
        message = "This sign-in link has expired. Start again from Sonia’s Settings › Connections."
    elif error:
        message = "Sign-in was cancelled. You can close this window."
    else:
        message = f"Connecting {html.escape(flow.name)} to Sonia… You can close this window."
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        "<title>Sonia</title><body style='font:15px system-ui;padding:40px;color:#302a23;background:#f4eddf'>"
        f"<p>{message}</p><script>setTimeout(function(){{window.close()}},1500)</script>")


@router.post("/{connection_id}/oauth/reconnect")
async def reconnect_oauth_connection(connection_id: str, user_id: str = Depends(current_user)):
    """Starts a new OAuth grant for an existing connection without creating a second one."""
    connection = await store.get_connection(user_id, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    if connection["auth_type"] != "oauth":
        raise HTTPException(status_code=422, detail="Only OAuth connections can be reconnected.")
    try:
        # Confirm that the replacement credentials can be persisted before opening a browser.
        store.encrypt_secret({"check": True})
        flow_id, authorization_url = await oauth.start_flow(
            user_id, connection["name"], connection["url"], connection_id=connection_id)
    except store.SecretKeyMissing as error:
        raise HTTPException(status_code=503, detail=str(error))
    except Exception as error:
        logger.info("Couldn't restart OAuth for %s: %r", connection["url"], error)
        raise HTTPException(status_code=400, detail="Couldn't start sign-in for that server. Please try again.")
    return {"flow_id": flow_id, "authorization_url": authorization_url}


@router.post("/{connection_id}/refresh")
async def refresh_mcp_connection(connection_id: str, user_id: str = Depends(current_user)):
    connection = await store.get_connection(user_id, connection_id, with_secret=True)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        tools, icon_url = await _tools_or_400(connection, user_id)
    except HTTPException as error:
        await store.update_connection(user_id, connection_id, last_error=error.detail)
        raise
    return await store.update_connection(user_id, connection_id, tools=tools, icon_url=icon_url, last_error=None)


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
