"""Private Cloudflare R2 storage. Only object keys are persisted in Postgres.

Every object of an upload lives under one per-user, per-chat prefix:
    users/{user_id}/chats/{chat_id}/documents/{document_id}/source.pdf
    users/{user_id}/chats/{chat_id}/documents/{document_id}/images/{image_id}.{ext}
"""

import os
import re

import boto3
from botocore.config import Config

# Uploads made without a chat (e.g. direct API calls) are kept apart from real chats.
UNASSIGNED_CHAT = "unassigned"
ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


def valid_chat_id(chat_id: str | None) -> bool:
    return chat_id is None or bool(ID_PATTERN.fullmatch(chat_id))


def document_prefix(user_id: str, chat_id: str | None, document_id: int) -> str:
    if not ID_PATTERN.fullmatch(user_id or ""):
        raise ValueError("user_id is not a safe path segment")
    if not valid_chat_id(chat_id):
        raise ValueError("chat_id may only contain letters, digits, '-' and '_' (max 64)")
    return f"users/{user_id}/chats/{chat_id or UNASSIGNED_CHAT}/documents/{document_id}"


class R2ImageStorage:
    def __init__(self, client, bucket: str, expires_in: int = 900):
        self.client = client
        self.bucket = bucket
        self.expires_in = expires_in

    @classmethod
    def from_env(cls):
        names = ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME")
        values = {name: os.getenv(name, "").strip() for name in names}
        if not any(values.values()):
            return None
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ValueError(f"Incomplete R2 configuration; missing: {', '.join(missing)}")
        expires_in = int(os.getenv("R2_IMAGE_URL_TTL", "900"))
        if not 1 <= expires_in <= 604800:
            raise ValueError("R2_IMAGE_URL_TTL must be between 1 and 604800 seconds")
        client = boto3.client(
            "s3", endpoint_url=values["R2_ENDPOINT_URL"],
            aws_access_key_id=values["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=values["R2_SECRET_ACCESS_KEY"],
            region_name="auto", config=Config(signature_version="s3v4"),
        )
        return cls(client, values["R2_BUCKET_NAME"], expires_in)

    def upload_pdf(self, prefix: str, data: bytes) -> str:
        key = f"{prefix}/source.pdf"
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data,
                               ContentType="application/pdf")
        return key

    def upload(self, prefix: str, image: dict) -> str:
        key = f"{prefix}/images/{image['image_id']}.{image['extension']}"
        self.client.put_object(Bucket=self.bucket, Key=key, Body=image["data"],
                               ContentType=image["content_type"])
        return key

    def delete(self, key: str):
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def sign(self, key: str) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.expires_in,
        )
