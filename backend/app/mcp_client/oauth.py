"""OAuth for MCP servers that require sign-in (e.g. "Login with Notion").

The MCP SDK's OAuthClientProvider does discovery, dynamic client registration, PKCE, the
code exchange and refreshes; it expects the browser round trip to happen in-process. Here
that round trip spans two HTTP requests, so a flow runs as a background task:

  POST /mcp-connections/oauth/start  -> task starts; its redirect handler hands back the
                                        authorization URL, which the browser opens
  GET  /mcp-connections/oauth/callback?code&state  (the provider's redirect)
                                     -> resumes the task, which finishes the exchange,
                                        lists the server's tools and saves the connection
  GET  /mcp-connections/oauth/status/{flow_id}     -> the settings page polls this

Flows live in memory (one API instance); one that isn't finished in 10 minutes is dropped.
Tokens and the registered client are stored encrypted with the connection and refreshed
by the SDK when they expire.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from app.mcp_client import store
from app.mcp_client.session import fetch_tools

logger = logging.getLogger(__name__)

CALLBACK_PATH = "/mcp-connections/oauth/callback"
FLOW_TIMEOUT = 600
_flows: dict[str, "Flow"] = {}


class ReauthorizationRequired(RuntimeError):
    """The connection's tokens can't be refreshed; the user has to sign in again."""


def needs_reauthorization(error: BaseException) -> bool:
    """AnyIO wraps authentication failures in task groups; retain their actionable reason."""
    return isinstance(error, ReauthorizationRequired) or (
        isinstance(error, BaseExceptionGroup) and any(needs_reauthorization(child) for child in error.exceptions))


def _public_api_url() -> str:
    return os.getenv("PUBLIC_API_URL", "http://localhost:8000").strip().rstrip("/")


def client_metadata() -> OAuthClientMetadata:
    return OAuthClientMetadata(
        client_name="Sonia",
        client_uri=os.getenv("FRONTEND_PUBLIC_URL", "https://sonia-ai-murp.vercel.app"),
        redirect_uris=[f"{_public_api_url()}{CALLBACK_PATH}"],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )


class SecretStorage:
    """TokenStorage over the connection's encrypted secret: {"tokens": …, "client_info": …}."""

    def __init__(self, secret: dict | None = None, user_id: str | None = None, connection_id: str | None = None):
        self.secret = dict(secret or {})
        self.user_id, self.connection_id = user_id, connection_id

    async def _save(self):
        if self.connection_id:
            await store.update_connection(self.user_id, self.connection_id, secret=self.secret)

    async def get_tokens(self) -> OAuthToken | None:
        tokens = self.secret.get("tokens")
        return OAuthToken.model_validate(tokens) if tokens else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.secret["tokens"] = tokens.model_dump(mode="json", exclude_none=True)
        await self._save()

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        info = self.secret.get("client_info")
        return OAuthClientInformationFull.model_validate(info) if info else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.secret["client_info"] = client_info.model_dump(mode="json", exclude_none=True)
        await self._save()


async def _needs_reauthorization(_url: str) -> None:
    raise ReauthorizationRequired("Sign in to this server again from Settings › Connections.")


async def _no_callback() -> AuthorizationCodeResult:
    raise ReauthorizationRequired("Sign in to this server again from Settings › Connections.")


def provider_for(user_id: str, connection: dict) -> OAuthClientProvider:
    """Auth for an existing OAuth connection; refreshed tokens are saved back."""
    storage = SecretStorage(connection.get("secret"), user_id, connection["id"])
    return OAuthClientProvider(connection["url"], client_metadata(), storage,
                               redirect_handler=_needs_reauthorization, callback_handler=_no_callback)


@dataclass
class Flow:
    user_id: str
    name: str
    url: str
    connection_id: str | None = None
    started: float = field(default_factory=time.monotonic)
    callback: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())
    task: asyncio.Task | None = None
    status: str = "pending"          # pending | done | error
    error: str | None = None
    connection: dict | None = None


def _expire_old_flows():
    now = time.monotonic()
    for state, flow in list(_flows.items()):
        if now - flow.started > FLOW_TIMEOUT:
            if flow.task and not flow.task.done():
                flow.task.cancel()
            _flows.pop(state, None)


async def start_flow(user_id: str, name: str, url: str, connection_id: str | None = None) -> tuple[str, str]:
    """Begins sign-in to an MCP server; returns (flow id, authorization URL to open).

    ``connection_id`` replaces the credentials on an existing OAuth connection after
    reauthorization instead of creating a duplicate connection.
    """
    _expire_old_flows()
    storage = SecretStorage()
    authorization_url: asyncio.Future = asyncio.get_running_loop().create_future()
    flow = Flow(user_id, name, url, connection_id)

    async def redirect(auth_url: str) -> None:
        state = (parse_qs(urlsplit(auth_url).query).get("state") or [""])[0]
        if not state:
            raise RuntimeError("The authorization URL has no state")
        _flows[state] = flow
        authorization_url.set_result((state, auth_url))

    async def callback() -> AuthorizationCodeResult:
        return await asyncio.wait_for(flow.callback, FLOW_TIMEOUT)

    provider = OAuthClientProvider(url, client_metadata(), storage, redirect_handler=redirect, callback_handler=callback)

    async def complete():
        try:
            tools, icon_url = await fetch_tools({"url": url, "auth_type": "oauth"}, auth=provider,
                                                 include_server_info=True)
            if connection_id:
                flow.connection = await store.update_connection(
                    user_id, connection_id, secret=storage.secret, tools=tools, icon_url=icon_url, last_error=None)
                if flow.connection is None:
                    raise RuntimeError("The connection was removed while signing in")
            else:
                flow.connection = await store.create_connection(user_id, name, url, "oauth", storage.secret, tools,
                                                                icon_url)
            flow.status = "done"
        except Exception as error:
            logger.info("MCP OAuth flow for %s failed: %r", url, error)
            flow.status, flow.error = "error", "Signing in to that server didn't complete. Please try again."
        if not authorization_url.done():
            authorization_url.set_exception(RuntimeError(flow.error or "The server didn't ask for sign-in."))

    flow.task = asyncio.create_task(complete())
    return await asyncio.wait_for(authorization_url, 30)


def finish_flow(state: str, code: str | None, error: str | None, iss: str | None) -> "Flow | None":
    """Hands the provider's redirect to the waiting flow; None if the state is unknown."""
    flow = _flows.get(state)
    if flow is None or flow.callback.done():
        return None
    if error or not code:
        flow.callback.set_exception(RuntimeError(error or "No authorization code"))
    else:
        flow.callback.set_result(AuthorizationCodeResult(code=code, state=state, iss=iss))
    return flow


def flow_status(user_id: str, flow_id: str) -> dict | None:
    flow = _flows.get(flow_id)
    if flow is None or flow.user_id != user_id:
        return None
    result = {"status": flow.status, "error": flow.error}
    if flow.status == "done" and flow.connection:
        result["connection"] = flow.connection
    if flow.status != "pending":
        _flows.pop(flow_id, None)
    return result
