import io
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.core.auth import current_user
from app.api import profiles
from test_image_pipeline import FakePool


def photo(size=(900, 600)):
    output = io.BytesIO()
    Image.new("RGB", size, "#e04035").save(output, "PNG")
    return output.getvalue()


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.pool = FakePool()
        self.row = {"display_name": "Sumit", "bio": "Research", "reduce_motion": False,
                    "compact_mode": True, "avatar_key": "users/user-1/profile/avatars/old.webp"}
        self.pool.conn.fetchrow.return_value = self.row
        self.pool.conn.fetchval.return_value = self.row["avatar_key"]
        self.storage = Mock(bucket="test", expires_in=900)
        self.storage.sign.return_value = "https://r2.test/temporary-signed-photo"
        for name, value in [("get_pool", AsyncMock(return_value=self.pool)),
                            ("ensure_profile_schema", AsyncMock()),
                            ("avatar_storage", Mock(return_value=self.storage))]:
            patcher = patch.object(profiles, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(profiles.R2ImageStorage, "from_env", return_value=self.storage)
        patcher.start()
        self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(profiles.router)
        app.dependency_overrides[current_user] = lambda: "user-1"
        self.app = app
        self.client = TestClient(app)

    def test_profile_reads_only_verified_account_and_never_returns_object_key(self):
        response = self.client.get("/profile")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("avatar_key", response.json())
        self.assertIn("avatar_expires_at", response.json())
        self.assertEqual(self.pool.conn.fetchrow.call_args.args[1], "user-1")
        self.storage.sign.assert_called_once_with(self.row["avatar_key"])

    def test_authentication_required(self):
        self.app.dependency_overrides.clear()
        self.assertEqual(self.client.get("/profile").status_code, 401)
        self.assertEqual(self.client.post("/profile/avatar", files={"file": ("p.png", photo(), "image/png")}).status_code, 401)

    def test_update_uses_owner_from_token_and_preserves_avatar(self):
        response = self.client.put("/profile", json={"display_name": "  Sonia reader  ", "bio": "Hi", "compact_mode": True, "user_id": "other"})
        self.assertEqual(response.status_code, 200)
        sql, owner, name, bio, motion, compact = self.pool.conn.fetchrow.call_args.args
        self.assertEqual((owner, name, bio, compact), ("user-1", "Sonia reader", "Hi", True))
        self.assertNotIn("avatar_key =", sql)

    def test_upload_normalizes_and_scopes_image_then_cleans_old_photo(self):
        response = self.client.post("/profile/avatar", files={"file": ("../malicious.png", photo(), "image/png")})
        self.assertEqual(response.status_code, 200)
        upload = self.storage.client.put_object.call_args.kwargs
        self.assertTrue(upload["Key"].startswith("users/user-1/profile/avatars/"))
        self.assertNotIn("malicious", upload["Key"])
        self.assertEqual(upload["ContentType"], "image/webp")
        with Image.open(io.BytesIO(upload["Body"])) as image:
            self.assertEqual(image.size, (512, 512))
            self.assertEqual(image.format, "WEBP")
            self.assertNotIn("exif", image.info)
        self.storage.delete.assert_called_once_with(self.row["avatar_key"])
        self.assertIn("pg_advisory_xact_lock", self.pool.conn.execute.call_args.args[0])

    def test_spoofed_image_is_rejected_before_r2(self):
        response = self.client.post("/profile/avatar", files={"file": ("evil.png", b"<svg onload='evil' />", "image/png")})
        self.assertEqual(response.status_code, 422)
        self.storage.client.put_object.assert_not_called()

    def test_oversized_upload_rejected(self):
        with patch.object(profiles, "MAX_AVATAR_BYTES", 10):
            response = self.client.post("/profile/avatar", files={"file": ("p.png", photo(), "image/png")})
        self.assertEqual(response.status_code, 413)
        self.storage.client.put_object.assert_not_called()

    def test_decompression_limit_checked_before_upload(self):
        with patch.object(profiles, "MAX_AVATAR_PIXELS", 100):
            response = self.client.post("/profile/avatar", files={"file": ("p.png", photo(), "image/png")})
        self.assertEqual(response.status_code, 422)
        self.storage.client.put_object.assert_not_called()

    def test_failed_database_write_removes_new_object_not_existing_photo(self):
        self.pool.conn.fetchrow.side_effect = RuntimeError("db unavailable")
        response = self.client.post("/profile/avatar", files={"file": ("p.png", photo(), "image/png")})
        self.assertEqual(response.status_code, 503)
        uploaded_key = self.storage.client.put_object.call_args.kwargs["Key"]
        self.storage.delete.assert_called_once_with(uploaded_key)
        self.assertNotEqual(uploaded_key, self.row["avatar_key"])

    def test_remove_updates_only_owner_and_deletes_current_photo(self):
        self.pool.conn.fetchrow.return_value = {**self.row, "avatar_key": None}
        response = self.client.delete("/profile/avatar")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["avatar_url"])
        sql, owner = self.pool.conn.fetchrow.call_args.args
        self.assertIn("WHERE user_id = $1", sql)
        self.assertEqual(owner, "user-1")
        self.storage.delete.assert_called_once_with(self.row["avatar_key"])

    def test_long_name_rejected(self):
        self.assertEqual(self.client.put("/profile", json={"display_name": "x" * 101}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
