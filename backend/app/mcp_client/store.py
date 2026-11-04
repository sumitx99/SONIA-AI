"""The user's MCP server connections. Secrets (headers, OAuth tokens) are encrypted at rest."""

import json
import os

from cryptography.fernet import Fernet, InvalidToken

from app.core.db import get_pool

MAX_CONNECTIONS = 10
POLICIES = ("allow", "ask", "off")
_schema_ready = False


class SecretKeyMissing(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = os.getenv("MCP_SECRET_KEY", "").strip()
    if not key:
        raise SecretKeyMissing("MCP_SECRET_KEY is not set, so connection secrets can't be stored.")
    return Fernet(key.encode())


def encrypt_secret(secret: dict | None) -> bytes | None:
    return _fernet().encrypt(json.dumps(secret).encode()) if secret else None


def decrypt_secret(blob: bytes | None) -> dict | None:
    if not blob:
        return None
    try:
        return json.loads(_fernet().decrypt(bytes(blob)))
    except InvalidToken:
        raise SecretKeyMissing("The connection's secret can't be read; MCP_SECRET_KEY may have changed.") from None


def default_policy(tool: dict) -> str:
    # Tools that only read run without asking; anything that may change something asks first.
    return "allow" if tool.get("read_only") else "ask"


async def ensure_connection_schema():
    global _schema_ready
    if _schema_ready:
        return
    async with (await get_pool()).acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS mcp_connections (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                auth_type TEXT NOT NULL CHECK (auth_type IN ('none', 'header', 'oauth')),
                secret BYTEA,
                tools JSONB NOT NULL DEFAULT '[]'::jsonb,
                tool_policies JSONB NOT NULL DEFAULT '{}'::jsonb,
                enabled BOOLEAN NOT NULL DEFAULT true,
                last_error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS mcp_connections_user_idx ON mcp_connections(user_id);
            ALTER TABLE mcp_connections ENABLE ROW LEVEL SECURITY;
        """)
    _schema_ready = True


def _row(row, with_secret=False) -> dict:
    tools = json.loads(row["tools"]) if isinstance(row["tools"], str) else row["tools"]
    policies = json.loads(row["tool_policies"]) if isinstance(row["tool_policies"], str) else row["tool_policies"]
    connection = {
        "id": str(row["id"]), "name": row["name"], "url": row["url"], "auth_type": row["auth_type"],
        "enabled": row["enabled"], "last_error": row["last_error"],
        "created_at": row["created_at"].isoformat(),
        "tools": [{**tool, "policy": policies.get(tool["name"], default_policy(tool))} for tool in tools],
    }
    if with_secret:
        connection["secret"] = None
        if connection["auth_type"] != "none":
            try:
                connection["secret"] = decrypt_secret(row["secret"])
            except (SecretKeyMissing, ValueError):
                connection["unavailable_reason"] = "Stored credentials could not be read. Reconnect this service in Settings → Connections."
    return connection


_COLUMNS = "id, name, url, auth_type, secret, tools, tool_policies, enabled, last_error, created_at"


async def list_connections(user_id: str, *, enabled_only=False, with_secret=False) -> list[dict]:
    await ensure_connection_schema()
    sql = f"SELECT {_COLUMNS} FROM mcp_connections WHERE user_id = $1"
    if enabled_only:
        sql += " AND enabled"
    async with (await get_pool()).acquire() as conn:
        rows = await conn.fetch(sql + " ORDER BY created_at", user_id)
    return [_row(row, with_secret) for row in rows]


async def get_connection(user_id: str, connection_id: str, *, with_secret=False) -> dict | None:
    await ensure_connection_schema()
    async with (await get_pool()).acquire() as conn:
        row = await conn.fetchrow(f"SELECT {_COLUMNS} FROM mcp_connections WHERE user_id = $1 AND id = $2::uuid",
                                  user_id, connection_id)
    return _row(row, with_secret) if row else None


async def count_connections(user_id: str) -> int:
    await ensure_connection_schema()
    async with (await get_pool()).acquire() as conn:
        return await conn.fetchval("SELECT count(*) FROM mcp_connections WHERE user_id = $1", user_id)


async def create_connection(user_id, name, url, auth_type, secret, tools) -> dict:
    await ensure_connection_schema()
    async with (await get_pool()).acquire() as conn:
        row = await conn.fetchrow(
            f"INSERT INTO mcp_connections (user_id, name, url, auth_type, secret, tools) "
            f"VALUES ($1, $2, $3, $4, $5, $6::jsonb) RETURNING {_COLUMNS}",
            user_id, name, url, auth_type, encrypt_secret(secret), json.dumps(tools))
    return _row(row)


async def update_connection(user_id, connection_id, *, name=None, enabled=None, tool_policies=None,
                            tools=None, secret=None, last_error=...) -> dict | None:
    """Updates the given fields; `last_error` takes None to clear it."""
    await ensure_connection_schema()
    sets, values = [], [user_id, connection_id]

    def assign(column, value, cast=""):
        values.append(value)
        sets.append(f"{column} = ${len(values)}{cast}")

    if name is not None:
        assign("name", name)
    if enabled is not None:
        assign("enabled", enabled)
    if tool_policies is not None:
        assign("tool_policies", json.dumps(tool_policies), "::jsonb")
    if tools is not None:
        assign("tools", json.dumps(tools), "::jsonb")
    if secret is not None:
        assign("secret", encrypt_secret(secret))
    if last_error is not ...:
        assign("last_error", last_error)
    sets.append("updated_at = now()")
    async with (await get_pool()).acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE mcp_connections SET {', '.join(sets)} WHERE user_id = $1 AND id = $2::uuid RETURNING {_COLUMNS}",
            *values)
    return _row(row) if row else None


async def delete_connection(user_id: str, connection_id: str) -> bool:
    await ensure_connection_schema()
    async with (await get_pool()).acquire() as conn:
        status = await conn.execute("DELETE FROM mcp_connections WHERE user_id = $1 AND id = $2::uuid",
                                    user_id, connection_id)
    return status.endswith(" 1")
