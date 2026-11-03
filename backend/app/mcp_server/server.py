"""Sonia as an MCP server: MCP clients (Claude, Cursor, …) reach a user's documents at /mcp.

Login is OAuth 2.1 with Supabase Auth as the authorization server: an unauthenticated
request gets a 401 pointing at /.well-known/oauth-protected-resource/mcp, which names
Supabase; the client registers itself there, the user approves on Sonia's consent page
(/oauth/consent in the frontend) and the client receives an ordinary Supabase access
token, which this module verifies like any other.
"""

import asyncio
import logging
import os
from urllib.parse import urlparse

import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from app.core.auth import supabase_issuer, verify_claims

logger = logging.getLogger(__name__)

# Where this API is reachable from outside, e.g. https://sonia-api.onrender.com.
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "http://localhost:8000").strip().rstrip("/")
MCP_PATH = "/mcp"


class SupabaseTokenVerifier:
    """Accepts Supabase access tokens: OAuth-client tokens (with `client_id`) and app sessions."""

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = await asyncio.to_thread(verify_claims, token)
        except (jwt.PyJWTError, RuntimeError):
            return None
        return AccessToken(
            token=token,
            client_id=claims.get("client_id") or "sonia-app",
            # Supabase has no custom scopes; access is limited per user in every tool instead.
            scopes=[],
            expires_at=claims.get("exp"),
            subject=claims["sub"],
            claims={"iss": claims.get("iss")},
        )


def current_mcp_user() -> str:
    """The Supabase user id behind the current MCP request."""
    token = get_access_token()
    if token is None or not token.subject:
        raise PermissionError("Not signed in")
    return token.subject


def _allowed_hosts() -> list[str]:
    host = urlparse(PUBLIC_API_URL).netloc
    return [host, "localhost:*", "127.0.0.1:*"]


mcp = MCPServer(
    "Sonia",
    title="Sonia",
    description="Search and ask questions about the PDFs you uploaded to Sonia.",
    instructions=(
        "Sonia holds the user's uploaded PDF documents. Use list_documents to see them, "
        "search_documents to find passages, ask_sonia for a grounded answer, and get_image "
        "for a figure from a page. Results are the user's private documents."
    ),
    website_url="https://sonia-ai-murp.vercel.app",
    token_verifier=SupabaseTokenVerifier(),
    auth=AuthSettings(
        issuer_url=supabase_issuer() if os.getenv("SUPABASE_URL") else "http://localhost:54321/auth/v1",
        resource_server_url=f"{PUBLIC_API_URL}{MCP_PATH}",
        required_scopes=None,
        # Supabase issues no RFC 8707 resource indicators (tokens carry aud="authenticated",
        # which verify_claims checks along with the issuer), so there is no resource to match.
        validate_token_resource=False,
    ),
)


def build_mcp_app():
    """A fresh MCP ASGI app; its session manager can run only once, so one per app lifespan."""
    return mcp.streamable_http_app(
        streamable_http_path=MCP_PATH,
        # No per-connection state to lose when the free instance sleeps or restarts.
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=_allowed_hosts(),
            allowed_origins=[],
        ),
    )


class MCPMount:
    """ASGI app mounted at "/" that forwards to the MCP app built for the current lifespan."""

    def __init__(self):
        self.app = None

    async def __call__(self, scope, receive, send):
        if self.app is None:
            raise RuntimeError("The MCP app is not running")
        await self.app(scope, receive, send)


# Registers the tools on `mcp`.
from app.mcp_server import tools  # noqa: E402,F401
