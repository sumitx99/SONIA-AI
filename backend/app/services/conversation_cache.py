"""Best-effort Redis cache for account-scoped conversation-list responses."""

import hashlib
import json
import logging
import os

logger = logging.getLogger(__name__)
CACHE_TTL_SECONDS = 30

try:
    from redis.asyncio import Redis
except ImportError:  # Local installs without the cache dependency still use Postgres.
    Redis = None

_client = None
_warned_missing_dependency = False


def _cache_key(user_id: str) -> str:
    # Avoid placing account identifiers directly in Redis key names.
    owner = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return f"sonia:conversation-list:v1:{owner}"


def _redis_client():
    global _client, _warned_missing_dependency
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return None
    if Redis is None:
        if not _warned_missing_dependency:
            logger.warning("REDIS_URL is configured but the redis package is unavailable; using the database")
            _warned_missing_dependency = True
        return None
    if _client is None:
        try:
            _client = Redis.from_url(
                url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
                health_check_interval=30,
            )
        except Exception:
            logger.warning("Could not initialize the Redis conversation cache; using the database", exc_info=True)
            return None
    return _client


async def get_cached_conversations(user_id: str):
    client = _redis_client()
    if client is None:
        return None
    try:
        value = await client.get(_cache_key(user_id))
        if not value:
            return None
        response = json.loads(value)
        if isinstance(response, dict) and isinstance(response.get("conversations"), list):
            return response
        return None
    except Exception:
        logger.warning("Conversation-list cache read failed; using the database", exc_info=True)
        return None


async def cache_conversations(user_id: str, response: dict) -> None:
    client = _redis_client()
    if client is None:
        return
    try:
        value = json.dumps(response, separators=(",", ":"))
        await client.set(_cache_key(user_id), value, ex=CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("Conversation-list cache write failed", exc_info=True)


async def invalidate_conversations(user_id: str) -> None:
    client = _redis_client()
    if client is None:
        return
    try:
        await client.delete(_cache_key(user_id))
    except Exception:
        logger.warning("Conversation-list cache invalidation failed", exc_info=True)


async def close_conversation_cache() -> None:
    global _client
    client, _client = _client, None
    if client is not None:
        try:
            await client.aclose()
        except Exception:
            logger.warning("Could not close the Redis conversation cache client", exc_info=True)
