"""A tiny MCP server for trying Sonia's MCP connections locally.

    .venv/bin/python scripts/dev_notes_mcp.py                   # no sign-in
    DEV_MCP_TOKEN=secret123 .venv/bin/python scripts/dev_notes_mcp.py   # needs "Authorization: Bearer secret123"

Serves http://127.0.0.1:8014/mcp with three tools over an in-memory notebook:
read_note and list_notes (read-only, so Sonia runs them without asking) and
create_note (makes changes, so Sonia asks first). Sonia's backend must have
MCP_ALLOW_PRIVATE_URLS=true in .env to connect to 127.0.0.1. Development only.
"""

import os

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

NOTES = {
    "plan": "Launch the MCP client on Friday. Owner: Priya.",
    "groceries": "Milk, eggs, coffee.",
}
READ_ONLY = ToolAnnotations(read_only_hint=True)

server = MCPServer("Dev Notes", instructions="A small notebook for testing.")


@server.tool(title="List notes", annotations=READ_ONLY)
def list_notes() -> list[str]:
    """List the names of all notes."""
    return sorted(NOTES)


@server.tool(title="Read note", annotations=READ_ONLY)
def read_note(name: str) -> str:
    """Read a note by its name."""
    return NOTES.get(name, f"No note called {name!r}.")


@server.tool(title="Create note")
def create_note(name: str, text: str) -> str:
    """Create a note, or replace the text of an existing one."""
    NOTES[name] = text
    return f"Saved note {name!r}."


def require_token(app, token):
    """Refuses requests without "Authorization: Bearer <token>" (to try API-key connections)."""
    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            if headers.get(b"authorization", b"").decode() != f"Bearer {token}":
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"Missing or wrong token"})
                return
        await app(scope, receive, send)
    return guarded


if __name__ == "__main__":
    app = server.streamable_http_app(stateless_http=True, json_response=True)
    token = os.getenv("DEV_MCP_TOKEN", "").strip()
    print(f"Dev Notes MCP: http://127.0.0.1:8014/mcp ({'token required' if token else 'no sign-in'})")
    uvicorn.run(require_token(app, token) if token else app, host="127.0.0.1", port=8014, log_level="warning")
