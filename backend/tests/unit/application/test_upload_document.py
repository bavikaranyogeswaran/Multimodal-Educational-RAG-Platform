"""Unit tests for UploadDocumentUseCase.

All I/O (repository and storage) is mocked. A real pypdf-generated PDF is
used for the happy path to exercise the page-count validation path with an
actual PDF structure.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from unittest.mock import AsyncMock

import pypdf
import pytest

from app.application.commands.upload_document import (
    UploadDocumentCommand,
    UploadDocumentUseCase,
    _check_size,
)
from app.domain.enums import DocumentStatus, JobPriority, JobStatus, JobType
from app.domain.errors import UploadValidationError
from app.domain.scope import ScopeContext

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB for tests
_MAX_PAGES = 5


def _pdf_page_counter(data: bytes) -> int:
    return len(pypdf.PdfReader(io.BytesIO(data)).pages)


def _make_pdf(n_pages: int = 1) -> bytes:
    writer = pypdf.PdfWriter()
    for _ in range(n_pages):
        writer.add_page(pypdf.PageObject.create_blank_page(width=612, height=792))
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


@pytest.fixture
def pdf_data() -> bytes:
    return _make_pdf(1)


@pytest.fixture
def mock_document_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.save = AsyncMock()
    return repo


@pytest.fixture
def mock_job_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.save = AsyncMock()
    return repo


@pytest.fixture
def mock_storage() -> AsyncMock:
    storage = AsyncMock()
    storage.put = AsyncMock()
    return storage


@pytest.fixture
def use_case(
    mock_document_repo: AsyncMock,
    mock_job_repo: AsyncMock,
    mock_storage: AsyncMock,
) -> UploadDocumentUseCase:
    return UploadDocumentUseCase(
        document_repo=mock_document_repo,
        job_repo=mock_job_repo,
        storage=mock_storage,
        max_upload_bytes=_MAX_BYTES,
        max_upload_pages=_MAX_PAGES,
        page_counter=_pdf_page_counter,
    )


def _command(
    scope: ScopeContext, data: bytes, *, content_type: str = "application/pdf"
) -> UploadDocumentCommand:
    return UploadDocumentCommand(
        scope=scope,
        filename="lecture.pdf",
        content_type=content_type,
        data=data,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_returns_pending_status(
        self, use_case: UploadDocumentUseCase, scope: ScopeContext, pdf_data: bytes
    ) -> None:
        result = await use_case.execute(_command(scope, pdf_data))
        assert result.status == DocumentStatus.PENDING

    async def test_returns_document_id(
        self, use_case: UploadDocumentUseCase, scope: ScopeContext, pdf_data: bytes
    ) -> None:
        result = await use_case.execute(_command(scope, pdf_data))
        assert isinstance(result.document_id, uuid.UUID)

    async def test_page_count_in_result(
        self, use_case: UploadDocumentUseCase, scope: ScopeContext
    ) -> None:
        data = _make_pdf(3)
        result = await use_case.execute(_command(scope, data))
        assert result.page_count == 3

    async def test_storage_key_format(
        self,
        use_case: UploadDocumentUseCase,
        scope: ScopeContext,
        pdf_data: bytes,
        mock_storage: AsyncMock,
    ) -> None:
        result = await use_case.execute(_command(scope, pdf_data))
        expected_prefix = f"{scope.user_id}/{scope.knowledge_base_id}/"
        expected_suffix = "/original.pdf"
        key_used = mock_storage.put.call_args.args[0]
        assert key_used.startswith(expected_prefix)
        assert key_used.endswith(expected_suffix)
        assert str(result.document_id) in key_used

    async def test_storage_receives_exact_bytes(
        self,
        use_case: UploadDocumentUseCase,
        scope: ScopeContext,
        pdf_data: bytes,
        mock_storage: AsyncMock,
    ) -> None:
        await use_case.execute(_command(scope, pdf_data))
        call_args = mock_storage.put.call_args
        assert call_args.args[1] == pdf_data
        assert call_args.kwargs["content_type"] == "application/pdf"

    async def test_document_saved_before_storage_write(
        self,
        use_case: UploadDocumentUseCase,
        scope: ScopeContext,
        pdf_data: bytes,
        mock_document_repo: AsyncMock,
        mock_storage: AsyncMock,
    ) -> None:
        call_order: list[str] = []
        mock_document_repo.save.side_effect = lambda *_: call_order.append("save") or None
        mock_storage.put.side_effect = lambda *_a, **_k: call_order.append("put") or None
        await use_case.execute(_command(scope, pdf_data))
        assert call_order == ["save", "put"]

    async def test_job_type_is_document_ingestion(
        self,
        use_case: UploadDocumentUseCase,
        scope: ScopeContext,
        pdf_data: bytes,
        mock_job_repo: AsyncMock,
    ) -> None:
        await use_case.execute(_command(scope, pdf_data))
        job = mock_job_repo.save.call_args.args[0]
        assert job.job_type == JobType.DOCUMENT_INGESTION

    async def test_job_priority_is_interactive(
        self,
        use_case: UploadDocumentUseCase,
        scope: ScopeContext,
        pdf_data: bytes,
        mock_job_repo: AsyncMock,
    ) -> None:
        await use_case.execute(_command(scope, pdf_data))
        job = mock_job_repo.save.call_args.args[0]
        assert job.priority == JobPriority.INTERACTIVE

    async def test_job_status_is_pending(
        self,
        use_case: UploadDocumentUseCase,
        scope: ScopeContext,
        pdf_data: bytes,
        mock_job_repo: AsyncMock,
    ) -> None:
        await use_case.execute(_command(scope, pdf_data))
        job = mock_job_repo.save.call_args.args[0]
        assert job.status == JobStatus.PENDING

    async def test_job_payload_contains_document_id(
        self,
        use_case: UploadDocumentUseCase,
        scope: ScopeContext,
        pdf_data: bytes,
        mock_job_repo: AsyncMock,
    ) -> None:
        result = await use_case.execute(_command(scope, pdf_data))
        job = mock_job_repo.save.call_args.args[0]
        assert job.payload["document_id"] == str(result.document_id)
        assert job.payload["knowledge_base_id"] == str(scope.knowledge_base_id)
        assert job.payload["user_id"] == str(scope.user_id)

    async def test_checksum_is_sha256_of_data(
        self,
        use_case: UploadDocumentUseCase,
        scope: ScopeContext,
        pdf_data: bytes,
        mock_document_repo: AsyncMock,
    ) -> None:
        await use_case.execute(_command(scope, pdf_data))
        document = mock_document_repo.save.call_args.args[1]
        assert document.checksum == hashlib.sha256(pdf_data).hexdigest()


# ---------------------------------------------------------------------------
# Validation — content type
# ---------------------------------------------------------------------------


class TestContentTypeValidation:
    async def test_wrong_content_type_raises(
        self, use_case: UploadDocumentUseCase, scope: ScopeContext, pdf_data: bytes
    ) -> None:
        with pytest.raises(UploadValidationError, match="unsupported content type"):
            await use_case.execute(_command(scope, pdf_data, content_type="image/png"))

    async def test_octet_stream_raises(
        self, use_case: UploadDocumentUseCase, scope: ScopeContext, pdf_data: bytes
    ) -> None:
        with pytest.raises(UploadValidationError):
            await use_case.execute(
                _command(scope, pdf_data, content_type="application/octet-stream")
            )


# ---------------------------------------------------------------------------
# Validation — magic bytes
# ---------------------------------------------------------------------------


class TestMagicBytesValidation:
    async def test_non_pdf_bytes_raises(
        self, use_case: UploadDocumentUseCase, scope: ScopeContext
    ) -> None:
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        with pytest.raises(UploadValidationError, match="PDF signature"):
            await use_case.execute(_command(scope, png_header))

    async def test_empty_bytes_raises(
        self, use_case: UploadDocumentUseCase, scope: ScopeContext
    ) -> None:
        with pytest.raises(UploadValidationError, match="PDF signature"):
            await use_case.execute(_command(scope, b""))


# ---------------------------------------------------------------------------
# Validation — size
# ---------------------------------------------------------------------------


class TestSizeValidation:
    async def test_file_over_limit_raises(
        self, use_case: UploadDocumentUseCase, scope: ScopeContext
    ) -> None:
        oversized = b"%PDF" + b"\x00" * (_MAX_BYTES + 1)
        with pytest.raises(UploadValidationError, match="exceeds the"):
            await use_case.execute(_command(scope, oversized))

    async def test_file_exactly_at_limit_passes_size_check(self) -> None:
        _check_size(b"x" * 100, max_bytes=100)

    async def test_file_one_over_limit_fails_size_check(self) -> None:
        with pytest.raises(UploadValidationError):
            _check_size(b"x" * 101, max_bytes=100)


# ---------------------------------------------------------------------------
# Validation — page count
# ---------------------------------------------------------------------------


class TestPageCountValidation:
    async def test_pdf_over_page_limit_raises(
        self, use_case: UploadDocumentUseCase, scope: ScopeContext
    ) -> None:
        data = _make_pdf(_MAX_PAGES + 1)
        with pytest.raises(UploadValidationError, match="pages"):
            await use_case.execute(_command(scope, data))

    async def test_pdf_at_page_limit_is_accepted(
        self, use_case: UploadDocumentUseCase, scope: ScopeContext
    ) -> None:
        data = _make_pdf(_MAX_PAGES)
        result = await use_case.execute(_command(scope, data))
        assert result.page_count == _MAX_PAGES
