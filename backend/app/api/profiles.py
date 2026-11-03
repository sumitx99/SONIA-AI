"""Account-owned profile metadata and private R2 avatars."""
import asyncio
import io
import logging
import time
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from app.core.auth import current_user
from app.core.db import get_pool
from app.services.images.image_storage import ID_PATTERN, R2ImageStorage

router = APIRouter(prefix="/profile", tags=["Account"])
logger = logging.getLogger(__name__)
MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 16_000_000
_schema_ready = False
_schema_lock = None


async def ensure_profile_schema():
    global _schema_ready, _schema_lock
    if _schema_ready:
        return
    _schema_lock = _schema_lock or asyncio.Lock()
    async with _schema_lock:
        if _schema_ready:
            return
        async with (await get_pool()).acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL DEFAULT '',
                    bio TEXT NOT NULL DEFAULT '',
                    reduce_motion BOOLEAN NOT NULL DEFAULT FALSE,
                    compact_mode BOOLEAN NOT NULL DEFAULT FALSE,
                    avatar_key TEXT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
            """)
        _schema_ready = True


class ProfileInput(BaseModel):
    display_name: str = Field(default="", max_length=100)
    bio: str = Field(default="", max_length=500)
    reduce_motion: bool = False
    compact_mode: bool = False


def normalize_avatar(data: bytes) -> bytes:
    """Decode the actual image, bound its dimensions, crop and remove metadata."""
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise HTTPException(422, "Choose a PNG, JPEG, or WebP image.")
            if source.width * source.height > MAX_AVATAR_PIXELS:
                raise HTTPException(422, "Choose an image smaller than 16 megapixels.")
            image = ImageOps.exif_transpose(source).convert("RGBA")
            image = ImageOps.fit(image, (512, 512), method=Image.Resampling.LANCZOS)
            background = Image.new("RGB", image.size, "#f7f7f5")
            background.paste(image, mask=image.getchannel("A"))
            output = io.BytesIO()
            background.save(output, format="WEBP", quality=85)
            return output.getvalue()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422, "This image could not be read. Choose a PNG, JPEG, or WebP image.")


def profile_response(row, storage=None):
    result = {"display_name": "", "bio": "", "reduce_motion": False, "compact_mode": False,
              "avatar_url": None, "avatar_expires_at": None}
    if row:
        result.update({key: row[key] for key in ("display_name", "bio", "reduce_motion", "compact_mode")})
        if row["avatar_key"] and storage:
            result["avatar_url"] = storage.sign(row["avatar_key"])
            result["avatar_expires_at"] = int(time.time()) + storage.expires_in
    return result


def avatar_storage():
    storage = R2ImageStorage.from_env()
    if storage is None:
        raise HTTPException(503, "Avatar storage is not configured yet. Your other profile details can still be saved.")
    return storage


@router.get("")
async def get_profile(user_id: str = Depends(current_user)):
    await ensure_profile_schema()
    async with (await get_pool()).acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM user_profiles WHERE user_id = $1", user_id)
    return profile_response(row, R2ImageStorage.from_env())


@router.put("")
async def save_profile(payload: ProfileInput, user_id: str = Depends(current_user)):
    await ensure_profile_schema()
    async with (await get_pool()).acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO user_profiles (user_id, display_name, bio, reduce_motion, compact_mode)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id) DO UPDATE SET display_name = EXCLUDED.display_name,
                bio = EXCLUDED.bio, reduce_motion = EXCLUDED.reduce_motion,
                compact_mode = EXCLUDED.compact_mode, updated_at = now()
            RETURNING *
        """, user_id, payload.display_name.strip(), payload.bio.strip(), payload.reduce_motion, payload.compact_mode)
    return profile_response(row, R2ImageStorage.from_env())


async def delete_old_avatar(storage, key):
    if key:
        try:
            await asyncio.to_thread(storage.delete, key)
        except Exception:
            logger.warning("Could not remove a replaced profile avatar", exc_info=True)


@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), user_id: str = Depends(current_user)):
    if not ID_PATTERN.fullmatch(user_id):
        raise HTTPException(422, "Invalid account identifier.")
    data = await file.read(MAX_AVATAR_BYTES + 1)
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(413, "Choose an image smaller than 5 MB.")
    image = await asyncio.to_thread(normalize_avatar, data)
    storage = avatar_storage()
    key = f"users/{user_id}/profile/avatars/{uuid.uuid4().hex}.webp"
    await ensure_profile_schema()
    try:
        async with (await get_pool()).acquire() as conn:
            async with conn.transaction():
                # Serialize avatar replacement/removal across browser tabs and requests.
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"avatar:{user_id}")
                old_key = await conn.fetchval("SELECT avatar_key FROM user_profiles WHERE user_id = $1", user_id)
                await asyncio.to_thread(storage.client.put_object, Bucket=storage.bucket, Key=key,
                                        Body=image, ContentType="image/webp", CacheControl="private, max-age=300")
                row = await conn.fetchrow("""
                    INSERT INTO user_profiles (user_id, avatar_key) VALUES ($1, $2)
                    ON CONFLICT (user_id) DO UPDATE SET avatar_key = EXCLUDED.avatar_key, updated_at = now()
                    RETURNING *
                """, user_id, key)
                result = profile_response(row, storage)
    except Exception:
        await delete_old_avatar(storage, key)
        logger.exception("Avatar upload failed")
        raise HTTPException(503, "Your photo could not be saved. Please try again.")
    await delete_old_avatar(storage, old_key)
    return result


@router.delete("/avatar")
async def remove_avatar(user_id: str = Depends(current_user)):
    storage = avatar_storage()
    await ensure_profile_schema()
    async with (await get_pool()).acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"avatar:{user_id}")
            old_key = await conn.fetchval("SELECT avatar_key FROM user_profiles WHERE user_id = $1", user_id)
            row = await conn.fetchrow("UPDATE user_profiles SET avatar_key = NULL, updated_at = now() "
                                      "WHERE user_id = $1 RETURNING *", user_id)
    await delete_old_avatar(storage, old_key)
    return profile_response(row)
