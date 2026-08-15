"""Use case: upload a document to a Knowledge Base.

Validates the file, persists the Document row, writes the bytes to object
storage, and queues a DOCUMENT_INGESTION job. All three operations use the
same database session so a storage failure before commit leaves the DB clean.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pypdf
import pypdf.errors

from app.domain.documents.entities import Document
from app.domain.enums import DocumentStatus, JobPriority, JobStatus, JobType
from app.domain.errors import UploadValidationError
from app.domain.jobs.entities import ProcessingJob
from app.domain.ports.adapters import StoragePort
from app.domain.ports.repositories import DocumentRepository, JobRepository
from app.domain.scope import ScopeContext

_ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({"application/pdf"})
_PDF_MAGIC = b"%PDF"
_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class UploadDocumentCommand:
    scope: ScopeContext
    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class UploadDocumentResult:
    document_id: UUID
    status: DocumentStatus
    page_count: int


class UploadDocumentUseCase:
    """Orchestrates document validation, persistence and job creation."""

    def __init__(
        self,
        document_repo: DocumentRepository,
        job_repo: JobRepository,
        storage: StoragePort,
        *,
        max_upload_bytes: int,
        max_upload_pages: int,
    ) -> None:
        self._document_repo = document_repo
        self._job_repo = job_repo
        self._storage = storage
        self._max_upload_bytes = max_upload_bytes
        self._max_upload_pages = max_upload_pages

    async def execute(self, command: UploadDocumentCommand) -> UploadDocumentResult:
        _check_content_type(command.content_type)
        _check_magic(command.data)
        _check_size(command.data, self._max_upload_bytes)
        page_count = _count_pages(command.data, self._max_upload_pages)

        doc_id = uuid4()
        now = datetime.now(UTC)
        storage_key = (
            f"{command.scope.user_id}/"
            f"{command.scope.knowledge_base_id}/"
            f"{doc_id}/original.pdf"
        )
        checksum = hashlib.sha256(command.data).hexdigest()

        document = Document(
            id=doc_id,
            user_id=command.scope.user_id,
            knowledge_base_id=command.scope.knowledge_base_id,
            filename=command.filename,
            content_type="application/pdf",
            byte_size=len(command.data),
            storage_key=storage_key,
            checksum=checksum,
            page_count=page_count,
            created_at=now,
            updated_at=now,
        )

        await self._document_repo.save(command.scope, document)
        await self._storage.put(storage_key, command.data, content_type="application/pdf")

        job = ProcessingJob(
            id=uuid4(),
            job_type=JobType.DOCUMENT_INGESTION,
            priority=JobPriority.INTERACTIVE,
            status=JobStatus.PENDING,
            attempt_count=0,
            max_attempts=_MAX_ATTEMPTS,
            created_at=now,
            updated_at=now,
            payload={
                "document_id": str(doc_id),
                "knowledge_base_id": str(command.scope.knowledge_base_id),
                "user_id": str(command.scope.user_id),
            },
        )
        await self._job_repo.save(job)

        return UploadDocumentResult(
            document_id=doc_id,
            status=document.status,
            page_count=page_count,
        )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _check_content_type(content_type: str) -> None:
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise UploadValidationError(
            f"unsupported content type {content_type!r}; only application/pdf is accepted"
        )


def _check_magic(data: bytes) -> None:
    if data[:4] != _PDF_MAGIC:
        raise UploadValidationError("file does not start with a PDF signature (%PDF)")


def _check_size(data: bytes, max_bytes: int) -> None:
    if len(data) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise UploadValidationError(f"file exceeds the {limit_mb} MB upload limit")


def _count_pages(data: bytes, max_pages: int) -> int:
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        count = len(reader.pages)
    except pypdf.errors.PdfReadError as exc:
        raise UploadValidationError(f"could not read PDF: {exc}") from exc
    if count > max_pages:
        raise UploadValidationError(
            f"PDF has {count} pages; the upload limit is {max_pages}"
        )
    return count
