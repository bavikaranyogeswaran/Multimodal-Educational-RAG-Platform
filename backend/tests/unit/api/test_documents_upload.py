"""Unit tests for the document upload route handler.

Verifies HTTP contract: correct status code, response shape, and error
mapping. The application service is exercised end-to-end with mocked
repository and storage dependencies — no real DB or R2 calls.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pypdf
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.container import get_container
from app.api.dependencies.scope import get_kb_scope
from app.api.middleware.errors import register_exception_handlers
from app.api.routers.documents import router as documents_router
from app.configuration.settings import get_settings
from app.domain.knowledge_base.entities import KnowledgeBase
from app.domain.scope import ScopeContext
from app.infrastructure.database.session import get_session

_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)
_NOW = datetime(2026, 8, 25, tzinfo=UTC)

#: The index version this configuration writes. The Knowledge Base answers from the
#: same one unless a test says otherwise.
_WRITTEN_VERSION = 1

#: Distinguishes "the default Knowledge Base" from "deliberately absent".
_UNSET: Any = object()


def _make_pdf(n_pages: int = 1) -> bytes:
    writer = pypdf.PdfWriter()
    for _ in range(n_pages):
        writer.add_page(pypdf.PageObject.create_blank_page(width=612, height=792))
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _make_kb(*, active_index_version: int = _WRITTEN_VERSION) -> KnowledgeBase:
    """The Knowledge Base the upload is addressed to.

    Read on every upload now, because a document written under a version retrieval is not
    reading would be stored and then never found.
    """
    return KnowledgeBase(
        id=_KB_ID,
        user_id=_USER_ID,
        name="Cloud data science",
        created_at=_NOW,
        updated_at=_NOW,
        active_index_version=active_index_version,
    )


def _make_app(
    *,
    mock_session: AsyncMock,
    mock_storage: AsyncMock,
    max_upload_bytes: int = 200 * 1024 * 1024,
    max_upload_pages: int = 1500,
    knowledge_base: KnowledgeBase | None = _UNSET,
) -> FastAPI:
    app = FastAPI()

    mock_container = MagicMock()
    mock_container.storage = mock_storage

    mock_settings = MagicMock()
    mock_settings.storage.max_upload_bytes = max_upload_bytes
    mock_settings.storage.max_upload_pages = max_upload_pages
    mock_settings.embedding.index_version = _WRITTEN_VERSION

    kb = _make_kb() if knowledge_base is _UNSET else knowledge_base
    result = MagicMock()
    result.scalar_one_or_none.return_value = kb
    mock_session.execute = AsyncMock(return_value=result)

    async def _session_dep() -> AsyncIterator[AsyncMock]:
        yield mock_session

    app.dependency_overrides[get_kb_scope] = lambda: _SCOPE
    app.dependency_overrides[get_session] = _session_dep
    app.dependency_overrides[get_container] = lambda: mock_container
    app.dependency_overrides[get_settings] = lambda: mock_settings

    app.include_router(documents_router, prefix="/api/v1")
    register_exception_handlers(app)
    return app


def _upload_url() -> str:
    return f"/api/v1/knowledge-bases/{_KB_ID}/documents"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestUploadDocumentRoute:
    def test_valid_pdf_returns_201(self) -> None:
        session = AsyncMock()
        storage = AsyncMock()
        pdf = _make_pdf(1)

        with TestClient(_make_app(mock_session=session, mock_storage=storage)) as client:
            resp = client.post(
                _upload_url(),
                files={"file": ("lecture.pdf", pdf, "application/pdf")},
            )

        assert resp.status_code == 201

    def test_response_contains_document_id_and_status(self) -> None:
        session = AsyncMock()
        storage = AsyncMock()
        pdf = _make_pdf(1)

        with TestClient(_make_app(mock_session=session, mock_storage=storage)) as client:
            resp = client.post(
                _upload_url(),
                files={"file": ("lecture.pdf", pdf, "application/pdf")},
            )

        body = resp.json()
        assert "document_id" in body
        assert body["status"] == "PENDING"
        assert body["page_count"] == 1
        uuid.UUID(body["document_id"])  # validates format

    def test_session_commit_called(self) -> None:
        session = AsyncMock()
        storage = AsyncMock()
        pdf = _make_pdf(1)

        with TestClient(_make_app(mock_session=session, mock_storage=storage)) as client:
            client.post(
                _upload_url(),
                files={"file": ("lecture.pdf", pdf, "application/pdf")},
            )

        session.commit.assert_called_once()

    def test_storage_put_called_with_pdf_bytes(self) -> None:
        session = AsyncMock()
        storage = AsyncMock()
        pdf = _make_pdf(2)

        with TestClient(_make_app(mock_session=session, mock_storage=storage)) as client:
            client.post(
                _upload_url(),
                files={"file": ("notes.pdf", pdf, "application/pdf")},
            )

        storage.put.assert_called_once()
        assert storage.put.call_args.args[1] == pdf


# ---------------------------------------------------------------------------
# Validation errors → 422
# ---------------------------------------------------------------------------


class TestUploadValidationErrors:
    def test_wrong_mime_type_returns_422(self) -> None:
        session = AsyncMock()
        storage = AsyncMock()
        data = b"not a real pdf"

        with TestClient(_make_app(mock_session=session, mock_storage=storage)) as client:
            resp = client.post(
                _upload_url(),
                files={"file": ("image.png", data, "image/png")},
            )

        assert resp.status_code == 422

    def test_non_pdf_bytes_returns_422(self) -> None:
        session = AsyncMock()
        storage = AsyncMock()
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        with TestClient(_make_app(mock_session=session, mock_storage=storage)) as client:
            resp = client.post(
                _upload_url(),
                files={"file": ("bad.pdf", data, "application/pdf")},
            )

        assert resp.status_code == 422

    def test_too_many_pages_returns_422(self) -> None:
        session = AsyncMock()
        storage = AsyncMock()
        pdf = _make_pdf(3)

        with TestClient(
            _make_app(mock_session=session, mock_storage=storage, max_upload_pages=2)
        ) as client:
            resp = client.post(
                _upload_url(),
                files={"file": ("big.pdf", pdf, "application/pdf")},
            )

        assert resp.status_code == 422

    def test_oversized_file_returns_422(self) -> None:
        session = AsyncMock()
        storage = AsyncMock()
        data = b"%PDF" + b"\x00" * 200

        with TestClient(
            _make_app(mock_session=session, mock_storage=storage, max_upload_bytes=100)
        ) as client:
            resp = client.post(
                _upload_url(),
                files={"file": ("huge.pdf", data, "application/pdf")},
            )

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Uploading into an index that is not the one being read
# ---------------------------------------------------------------------------


class TestStaleIndexRefusal:
    """A document written under a version retrieval is not reading is a silent loss.

    Every step succeeds, the document reaches COMPLETED, and it answers nothing. There
    is no failure anywhere to find — only a textbook that has stopped saying anything.
    Refusing puts that where somebody can see it.
    """

    def test_upload_is_refused_while_the_index_is_stale(self) -> None:
        session = AsyncMock()
        storage = AsyncMock()

        app = _make_app(
            mock_session=session,
            mock_storage=storage,
            knowledge_base=_make_kb(active_index_version=_WRITTEN_VERSION + 1),
        )
        with TestClient(app) as client:
            resp = client.post(
                _upload_url(), files={"file": ("lecture.pdf", _make_pdf(1), "application/pdf")}
            )

        assert resp.status_code == 409

    def test_the_refusal_names_what_resolves_it(self) -> None:
        """Nothing else in the system will say this, and it is not something the caller
        can work out from a status code."""
        session = AsyncMock()

        app = _make_app(
            mock_session=session,
            mock_storage=AsyncMock(),
            knowledge_base=_make_kb(active_index_version=_WRITTEN_VERSION + 1),
        )
        with TestClient(app) as client:
            resp = client.post(
                _upload_url(), files={"file": ("lecture.pdf", _make_pdf(1), "application/pdf")}
            )

        assert "reindex" in resp.json()["detail"]

    def test_nothing_is_stored_when_the_upload_is_refused(self) -> None:
        """A refusal that still wrote the file would leave the bytes behind with no row
        naming them."""
        session = AsyncMock()
        storage = AsyncMock()

        app = _make_app(
            mock_session=session,
            mock_storage=storage,
            knowledge_base=_make_kb(active_index_version=_WRITTEN_VERSION + 1),
        )
        with TestClient(app) as client:
            client.post(
                _upload_url(), files={"file": ("lecture.pdf", _make_pdf(1), "application/pdf")}
            )

        storage.put.assert_not_awaited()
        session.commit.assert_not_awaited()

    def test_an_index_behind_the_written_version_is_refused_too(self) -> None:
        """A configuration rolled back leaves the same hole as one moved forward."""
        app = _make_app(
            mock_session=AsyncMock(),
            mock_storage=AsyncMock(),
            knowledge_base=_make_kb(active_index_version=_WRITTEN_VERSION + 5),
        )
        with TestClient(app) as client:
            resp = client.post(
                _upload_url(), files={"file": ("lecture.pdf", _make_pdf(1), "application/pdf")}
            )

        assert resp.status_code == 409

    def test_a_matching_index_is_not_refused(self) -> None:
        app = _make_app(
            mock_session=AsyncMock(),
            mock_storage=AsyncMock(),
            knowledge_base=_make_kb(active_index_version=_WRITTEN_VERSION),
        )
        with TestClient(app) as client:
            resp = client.post(
                _upload_url(), files={"file": ("lecture.pdf", _make_pdf(1), "application/pdf")}
            )

        assert resp.status_code == 201

    def test_a_missing_knowledge_base_is_a_404_not_a_409(self) -> None:
        app = _make_app(mock_session=AsyncMock(), mock_storage=AsyncMock(), knowledge_base=None)
        with TestClient(app) as client:
            resp = client.post(
                _upload_url(), files={"file": ("lecture.pdf", _make_pdf(1), "application/pdf")}
            )

        assert resp.status_code == 404
