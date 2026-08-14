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
from jwt.algorithms import RSAAlgorithm

from app.domain.errors import AuthenticationError


class JwksClient:
    """Fetches RS256 public keys from a JWKS endpoint and caches them by key ID."""

    def __init__(self, url: str, cache_seconds: int) -> None:
        self._url = url
        self._cache_seconds = cache_seconds
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched_at: float = 0.0

    async def get_rsa_key(self, kid: str) -> Any:
        """Return the RSA public key object for the given key ID.

        Refreshes the JWKS when the cache is empty or stale. Raises
        `AuthenticationError` when the key ID is not present after a fresh
        fetch — the token was signed by an unknown key.
        """
        await self._refresh_if_stale()
        key_data = self._keys.get(kid)
        if key_data is None:
            raise AuthenticationError(f"No signing key found for kid={kid!r}")
        return RSAAlgorithm.from_jwk(json.dumps(key_data))

    async def _refresh_if_stale(self) -> None:
        elapsed = time.monotonic() - self._fetched_at
        if self._keys and elapsed < self._cache_seconds:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self._url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AuthenticationError("Failed to fetch JWKS from Supabase") from exc
        # response.json() reads the already-buffered body — safe outside the context manager.
        data: dict[str, Any] = response.json()
        self._keys = {key["kid"]: key for key in data.get("keys", [])}
        self._fetched_at = time.monotonic()
