"""FastAPI dependency that resolves the calling user from the JWT."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.configuration.settings import get_settings
from app.domain.errors import AuthenticationError
from app.infrastructure.auth.jwks import JwksClient
from app.infrastructure.auth.jwt import extract_user_id

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> uuid.UUID:
    """Extract and verify the caller's identity from the Authorization header.

    Returns the user_id UUID from the JWT sub claim. Raises HTTP 401 on any
    authentication failure — missing header, malformed token, expired signature,
    wrong audience, or unknown signing key.
    """
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jwks_client: JwksClient = request.app.state.jwks_client
    settings = get_settings()

    try:
        return await extract_user_id(credentials.credentials, jwks_client, settings.supabase)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
