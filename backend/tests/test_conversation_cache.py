import asyncio
import hashlib
import unittest
from unittest.mock import patch

from app.services import conversation_cache


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.set_calls = []
        self.closed = False

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex):
        self.values[key] = value
        self.set_calls.append((key, value, ex))

    async def delete(self, key):
        self.values.pop(key, None)

    async def aclose(self):
        self.closed = True


class FakeRedisFactory:
    client = FakeRedis()

    @classmethod
    def from_url(cls, *_args, **_kwargs):
        return cls.client


class ConversationCacheTests(unittest.TestCase):
    def setUp(self):
        conversation_cache._client = None
        FakeRedisFactory.client = FakeRedis()
        self.environment = patch.dict("os.environ", {"REDIS_URL": "redis://cache.test/0"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.redis_patch = patch.object(conversation_cache, "Redis", FakeRedisFactory)
        self.redis_patch.start()
        self.addCleanup(self.redis_patch.stop)
        self.addCleanup(self.reset_client)

    @staticmethod
    def reset_client():
        conversation_cache._client = None

    def test_cached_response_is_user_scoped_and_uses_short_ttl(self):
        response = {"conversations": [{"id": "chat-1", "messages": []}]}
        key = "sonia:conversation-list:v1:" + hashlib.sha256(b"user-1").hexdigest()
        asyncio.run(conversation_cache.cache_conversations("user-1", response))
        self.assertEqual(asyncio.run(conversation_cache.get_cached_conversations("user-1")), response)
        self.assertIsNone(asyncio.run(conversation_cache.get_cached_conversations("user-2")))
        self.assertEqual(FakeRedisFactory.client.set_calls[0], (key, '{"conversations":[{"id":"chat-1","messages":[]}]}', 30))

    def test_redis_connection_errors_fall_back_without_raising(self):
        class UnavailableRedis(FakeRedis):
            async def get(self, _key):
                raise ConnectionError("unavailable")

        FakeRedisFactory.client = UnavailableRedis()
        self.assertIsNone(asyncio.run(conversation_cache.get_cached_conversations("user-1")))

    def test_malformed_cache_payload_is_treated_as_miss(self):
        key = "sonia:conversation-list:v1:" + hashlib.sha256(b"user-1").hexdigest()
        FakeRedisFactory.client.values[key] = "not-json"
        self.assertIsNone(asyncio.run(conversation_cache.get_cached_conversations("user-1")))


if __name__ == "__main__":
    unittest.main()
