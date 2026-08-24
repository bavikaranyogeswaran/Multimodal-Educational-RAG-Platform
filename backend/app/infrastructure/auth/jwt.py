"""JWT verification for Supabase access tokens (RS256 and ES256)."""

from __future__ import annotations

import uuid
from typing import Any

import jwt as pyjwt

from app.configuration.settings import SupabaseSettings
from app.domain.errors import AuthenticationError
from app.infrastructure.auth.jwks import JwksClient

#: Tolerance for disagreement between this machine's clock and Supabase's when comparing
#: the time claims. Without it a token minted a moment ago is rejected as not yet valid
#: whenever the local clock trails the issuer's, which no amount of retrying resolves.
_CLOCK_SKEW_LEEWAY_SECONDS = 60


async def extract_user_id(
    token: str,
    jwks_client: JwksClient,
    settings: SupabaseSettings,
) -> uuid.UUID:
    """Verify a Supabase RS256 JWT and return the user_id from the sub claim.

    Raises `AuthenticationError` on any failure: malformed token, missing kid,
    unknown signing key, expired signature, wrong audience, or a sub that is not
    a valid UUID.
    """
    try:
        header = pyjwt.get_unverified_header(token)
    except pyjwt.exceptions.DecodeError as exc:
        raise AuthenticationError("Malformed token header") from exc

    kid: str = header.get("kid", "")
    if not kid:
        raise AuthenticationError("Token header is missing the kid field")

    public_key: Any = await jwks_client.get_signing_key(kid)

    try:
        payload: dict[str, Any] = pyjwt.decode(
            token,
            public_key,
            algorithms=["RS256", "ES256"],
            audience=settings.jwt_audience,
            leeway=_CLOCK_SKEW_LEEWAY_SECONDS,
        )
    except pyjwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired") from exc
    except pyjwt.InvalidAudienceError as exc:
        raise AuthenticationError("Token audience does not match") from exc
    except pyjwt.InvalidTokenError as exc:
        raise AuthenticationError("Token validation failed") from exc

    sub: str = payload.get("sub", "")
    try:
        return uuid.UUID(sub)
    except (ValueError, AttributeError) as exc:
        raise AuthenticationError("Token sub claim is not a valid UUID") from exc
