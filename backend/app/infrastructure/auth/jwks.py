"""JWKS key fetching with in-memory TTL caching.

One `JwksClient` instance lives on `app.state` for the lifetime of the process.
Keys are refreshed only when the cache is empty or has passed its TTL — never on
every request.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from app.domain.errors import AuthenticationError


def _to_public_key(jwk: dict[str, Any]) -> Any:
    """Convert one JWK into the public key object pyjwt verifies signatures with."""
    algorithm = ECAlgorithm if jwk.get("kty") == "EC" else RSAAlgorithm
    return algorithm.from_jwk(json.dumps(jwk))


class JwksClient:
    """Fetches public keys from a JWKS endpoint and caches them by key ID.

    Supports both RSA (RS256) and EC (ES256) key types, selecting the right
    algorithm class from the `kty` field of each JWK. Keys are cached as usable
    key objects rather than raw JWK dicts, so a verification never has to build
    one while a request is waiting on it.
    """

    def __init__(self, url: str, cache_seconds: int) -> None:
        self._url = url
        self._cache_seconds = cache_seconds
        self._keys: dict[str, Any] = {}
        self._fetched_at: float = 0.0

    async def warm_up(self) -> None:
        """Populate the key cache ahead of the first request that needs it."""
        await self._refresh_if_stale()

    async def get_signing_key(self, kid: str) -> Any:
        """Return the public key object for the given key ID.

        Refreshes the JWKS when the cache is empty or stale. Raises
        `AuthenticationError` when the key ID is not present after a fresh
        fetch — the token was signed by an unknown key.
        """
        await self._refresh_if_stale()
        key = self._keys.get(kid)
        if key is None:
            raise AuthenticationError(f"No signing key found for kid={kid!r}")
        return key

    async def _refresh_if_stale(self) -> None:
        elapsed = time.monotonic() - self._fetched_at
        if self._keys and elapsed < self._cache_seconds:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self._url)
                response.raise_for_status()
                data: dict[str, Any] = response.json()
        except httpx.HTTPError as exc:
            raise AuthenticationError("Failed to fetch JWKS from Supabase") from exc
        self._keys = {jwk["kid"]: _to_public_key(jwk) for jwk in data.get("keys", [])}
        self._fetched_at = time.monotonic()
