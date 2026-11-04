from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import current_user
from app.services.images.web_images import owned_images, attachment
from app.services.images.image_storage import R2ImageStorage

router = APIRouter(prefix="/web-images", tags=["Web images"])


@router.get("/{image_id}")
async def renew_image(image_id: str, user_id: str = Depends(current_user)):
    if len(image_id) != 64 or any(char not in "0123456789abcdef" for char in image_id):
        raise HTTPException(404, "Image not found")
    rows = await owned_images(user_id, [image_id])
    if image_id not in rows:
        raise HTTPException(404, "Image not found")
    try:
        storage = R2ImageStorage.from_env()
    except ValueError:
        storage = None
    if not storage:
        raise HTTPException(503, "Image storage is unavailable")
    return attachment(rows[image_id], storage)
