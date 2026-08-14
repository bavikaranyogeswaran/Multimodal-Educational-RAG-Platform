"""Unit tests for R2StorageAdapter and R2CacheAdapter.

Uses a mock aioboto3 session and client; no real S3 calls are made.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.infrastructure.storage.r2 import R2CacheAdapter, R2StorageAdapter

_BUCKET = "test-bucket"
_ENDPOINT = "https://test.r2.cloudflare.com"
_PREFIX = "cache/renders"


def _make_client_mock() -> tuple[AsyncMock, Any]:
    """Return (inner_client, context_manager) pair for session.client()."""
    inner = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=inner)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return inner, ctx


def _make_session(ctx: Any) -> MagicMock:
    session = MagicMock()
    session.client.return_value = ctx
    return session


def _storage(session: Any) -> R2StorageAdapter:
    return R2StorageAdapter(session, bucket=_BUCKET, endpoint_url=_ENDPOINT)


def _cache(session: Any) -> R2CacheAdapter:
    return R2CacheAdapter(session, bucket=_BUCKET, endpoint_url=_ENDPOINT, prefix=_PREFIX)


# ---------------------------------------------------------------------------
# R2StorageAdapter
# ---------------------------------------------------------------------------


class TestR2StorageAdapterPut:
    async def test_put_calls_put_object_with_correct_args(self) -> None:
        inner, ctx = _make_client_mock()
        adapter = _storage(_make_session(ctx))

        await adapter.put("user/kb/doc/original.pdf", b"bytes", content_type="application/pdf")

        inner.put_object.assert_called_once_with(
            Bucket=_BUCKET,
            Key="user/kb/doc/original.pdf",
            Body=b"bytes",
            ContentType="application/pdf",
        )

    async def test_put_opens_client_with_endpoint(self) -> None:
        _inner, ctx = _make_client_mock()
        session = _make_session(ctx)
        await _storage(session).put("k", b"d", content_type="text/plain")

        session.client.assert_called_once_with("s3", endpoint_url=_ENDPOINT)


class TestR2StorageAdapterGet:
    async def test_get_returns_body_bytes(self) -> None:
        inner, ctx = _make_client_mock()
        body = AsyncMock()
        body.read.return_value = b"file-content"
        inner.get_object.return_value = {"Body": body}

        result = await _storage(_make_session(ctx)).get("user/kb/doc/original.pdf")

        assert result == b"file-content"
        inner.get_object.assert_called_once_with(Bucket=_BUCKET, Key="user/kb/doc/original.pdf")


class TestR2StorageAdapterDelete:
    async def test_delete_calls_delete_object(self) -> None:
        inner, ctx = _make_client_mock()
        await _storage(_make_session(ctx)).delete("user/kb/doc/original.pdf")

        inner.delete_object.assert_called_once_with(
            Bucket=_BUCKET, Key="user/kb/doc/original.pdf"
        )


class TestR2StorageAdapterPresignedUrl:
    async def test_presigned_url_passes_correct_params(self) -> None:
        inner, ctx = _make_client_mock()
        inner.generate_presigned_url.return_value = "https://r2.example.com/signed"

        url = await _storage(_make_session(ctx)).presigned_get_url(
            "user/kb/doc/original.pdf", expires_in=900
        )

        inner.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": _BUCKET, "Key": "user/kb/doc/original.pdf"},
            ExpiresIn=900,
        )
        assert url == "https://r2.example.com/signed"


# ---------------------------------------------------------------------------
# R2CacheAdapter
# ---------------------------------------------------------------------------


class TestR2CacheAdapterPut:
    async def test_put_prefixes_key_and_stores_ttl_metadata(self) -> None:
        inner, ctx = _make_client_mock()
        now_ts = 1_000_000

        with patch("time.time", return_value=float(now_ts)):
            await _cache(_make_session(ctx)).put("page/abc.png", b"img", ttl=3600)

        call_kwargs = inner.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == _BUCKET
        assert call_kwargs["Key"] == f"{_PREFIX}/page/abc.png"
        assert call_kwargs["Body"] == b"img"
        assert call_kwargs["Metadata"]["x-created-at"] == str(now_ts)
        assert call_kwargs["Metadata"]["x-ttl-seconds"] == "3600"


class TestR2CacheAdapterGet:
    async def test_get_returns_bytes_when_fresh(self) -> None:
        inner, ctx = _make_client_mock()
        body = AsyncMock()
        body.read.return_value = b"render"
        created = 1_000_000
        inner.get_object.return_value = {
            "Body": body,
            "Metadata": {"x-created-at": str(created), "x-ttl-seconds": "3600"},
        }

        with patch("time.time", return_value=float(created + 100)):
            result = await _cache(_make_session(ctx)).get("page/abc.png")

        assert result == b"render"
        inner.get_object.assert_called_once_with(
            Bucket=_BUCKET, Key=f"{_PREFIX}/page/abc.png"
        )

    async def test_get_returns_none_when_expired(self) -> None:
        inner, ctx = _make_client_mock()
        body = AsyncMock()
        body.read.return_value = b"render"
        created = 1_000_000
        inner.get_object.return_value = {
            "Body": body,
            "Metadata": {"x-created-at": str(created), "x-ttl-seconds": "3600"},
        }

        with patch("time.time", return_value=float(created + 4000)):
            result = await _cache(_make_session(ctx)).get("page/abc.png")

        assert result is None

    async def test_get_returns_none_on_no_such_key(self) -> None:
        inner, ctx = _make_client_mock()
        exc = ClientError(
            error_response={"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
            operation_name="GetObject",
        )
        inner.get_object.side_effect = exc

        result = await _cache(_make_session(ctx)).get("missing/key.png")

        assert result is None

    async def test_get_reraises_unexpected_client_errors(self) -> None:
        inner, ctx = _make_client_mock()
        exc = ClientError(
            error_response={"Error": {"Code": "AccessDenied", "Message": "Denied"}},
            operation_name="GetObject",
        )
        inner.get_object.side_effect = exc

        with pytest.raises(ClientError):
            await _cache(_make_session(ctx)).get("key.png")

    async def test_get_returns_bytes_when_no_metadata(self) -> None:
        inner, ctx = _make_client_mock()
        body = AsyncMock()
        body.read.return_value = b"legacy"
        inner.get_object.return_value = {"Body": body, "Metadata": {}}

        result = await _cache(_make_session(ctx)).get("page/abc.png")

        assert result == b"legacy"


class TestR2CacheAdapterDelete:
    async def test_delete_uses_prefixed_key(self) -> None:
        inner, ctx = _make_client_mock()
        await _cache(_make_session(ctx)).delete("page/abc.png")

        inner.delete_object.assert_called_once_with(
            Bucket=_BUCKET, Key=f"{_PREFIX}/page/abc.png"
        )
