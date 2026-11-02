"""Supabase Auth: every API request carries the user's access token as a Bearer header."""

import os
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException

AUDIENCE = "authenticated"


@lru_cache(maxsize=1)
def _jwks_client():
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    if not url:
        raise RuntimeError("SUPABASE_URL is not configured")
    # Public signing keys are cached; a new key id triggers one refetch.
    return jwt.PyJWKClient(f"{url}/auth/v1/.well-known/jwks.json", cache_keys=True)


def verify_token(token: str) -> str:
    """Returns the Supabase user id for a valid access token."""
    header = jwt.get_unverified_header(token)
    if header.get("alg") == "HS256":
        # Projects still on the legacy shared secret.
        secret = os.getenv("SUPABASE_JWT_SECRET", "").strip()
        if not secret:
            raise jwt.InvalidTokenError("HS256 token but SUPABASE_JWT_SECRET is not set")
        claims = jwt.decode(token, secret, algorithms=["HS256"], audience=AUDIENCE)
    else:
        key = _jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["ES256", "RS256"], audience=AUDIENCE)
    user_id = claims.get("sub")
    if not user_id:
        raise jwt.InvalidTokenError("Token has no subject")
    return user_id


def current_user(authorization: str | None = Header(None)) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Please sign in to continue.",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        return verify_token(token)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error))
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.",
                            headers={"WWW-Authenticate": "Bearer"})
