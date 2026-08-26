"""Document resource endpoints."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pypdf
import pypdf.errors
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.container import get_container
from app.api.dependencies.scope import get_kb_scope
from app.api.schemas.document import (
    DocumentResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
    DocumentUrlResponse,
)
from app.application.commands.upload_document import (
    UploadDocumentCommand,
    UploadDocumentUseCase,
)
from app.configuration.container import Container
from app.configuration.settings import Settings, get_settings
from app.domain.enums import JobPriority, JobStatus, JobType
from app.domain.errors import UploadValidationError
from app.domain.jobs.entities import ProcessingJob
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.document import SqlDocumentRepository
from app.infrastructure.database.repositories.job import SqlJobRepository
from app.infrastructure.database.repositories.knowledge_base import (
    SqlKnowledgeBaseRepository,
)
from app.infrastructure.database.session import get_session

_404_DOCUMENT = "Document not found"


def _count_pdf_pages(data: bytes) -> int:
    try:
        return len(pypdf.PdfReader(io.BytesIO(data)).pages)
    except pypdf.errors.PdfReadError as exc:
        raise UploadValidationError(f"could not read PDF: {exc}") from exc


router = APIRouter(
    prefix="/knowledge-bases/{kb_id}/documents",
    tags=["documents"],
    dependencies=[Depends(get_kb_scope)],
)

#: Returned when a Knowledge Base is not reading from the version an ingestion would
#: write. Named for what the caller has to do about it, since nothing else here will.
_409_STALE_INDEX = (
    "This knowledge base is not reading from the index new documents would be written "
    "to, so a document uploaded now would be stored and then never found. Rebuild it "
    "first: POST /knowledge-bases/{kb_id}/reindex."
)


async def _refuse_while_the_index_is_stale(
    scope: ScopeContext, session: AsyncSession, settings: Settings
) -> None:
    """Reject an upload that would produce a document nothing can retrieve.

    The alternative is worse than a refusal. An upload accepted here succeeds at every
    step, reaches COMPLETED, and is invisible — there is no failure anywhere to look at,
    only a textbook that answers nothing. Refusing puts the problem where somebody can
    see it, and names the one operation that resolves it.

    The window is real but narrow: it opens when the embedding model is reconfigured, and
    while a rebuild is running. Both are maintenance, and declining writes during
    maintenance is the ordinary thing to do.
    """
    kb = await SqlKnowledgeBaseRepository(scope, session).get(scope)
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    if kb.index_is_stale(written_version=settings.embedding.index_version):
        raise HTTPException(status_code=409, detail=_409_STALE_INDEX)


@router.post("", status_code=201)
async def upload_document(
    file: UploadFile,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
    container: Annotated[Container, Depends(get_container)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentUploadResponse:
    await _refuse_while_the_index_is_stale(scope, session, settings)
    data = await file.read()
    use_case = UploadDocumentUseCase(
        document_repo=SqlDocumentRepository(scope, session),
        job_repo=SqlJobRepository(session),
        storage=container.storage,
        max_upload_bytes=settings.storage.max_upload_bytes,
        max_upload_pages=settings.storage.max_upload_pages,
        page_counter=_count_pdf_pages,
    )
    result = await use_case.execute(
        UploadDocumentCommand(
            scope=scope,
            filename=file.filename or "upload.pdf",
            content_type=file.content_type or "application/pdf",
            data=data,
        )
    )
    await session.commit()
    return DocumentUploadResponse(
        document_id=result.document_id,
        status=result.status,
        page_count=result.page_count,
    )


@router.get("", status_code=200)
async def list_documents(
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DocumentResponse]:
    docs = await SqlDocumentRepository(scope, session).list(scope)
    return [DocumentResponse.model_validate(doc) for doc in docs]


@router.get("/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentResponse:
    doc = await SqlDocumentRepository(scope, session).get(scope, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=_404_DOCUMENT)
    return DocumentResponse.model_validate(doc)


@router.get("/{document_id}/status")
async def get_document_status(
    document_id: uuid.UUID,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentStatusResponse:
    doc = await SqlDocumentRepository(scope, session).get(scope, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=_404_DOCUMENT)
    return DocumentStatusResponse.model_validate(doc)


_URL_TTL_SECONDS = 300  # 5-minute window — long enough to load a PDF, short enough to limit exposure


@router.get("/{document_id}/url")
async def get_document_url(
    document_id: uuid.UUID,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
    container: Annotated[Container, Depends(get_container)],
) -> DocumentUrlResponse:
    doc = await SqlDocumentRepository(scope, session).get(scope, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=_404_DOCUMENT)
    url = await container.storage.presigned_get_url(
        doc.storage_key, expires_in=_URL_TTL_SECONDS
    )
    return DocumentUrlResponse(
        url=url,
        expires_at=datetime.now(UTC) + timedelta(seconds=_URL_TTL_SECONDS),
    )


@router.delete("/{document_id}", status_code=202)
async def delete_document(
    document_id: uuid.UUID,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentStatusResponse:
    repo = SqlDocumentRepository(scope, session)
    doc = await repo.get(scope, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=_404_DOCUMENT)
    now = datetime.now(UTC)
    deleting = doc.mark_deleting(now=now)
    await repo.save(scope, deleting)
    job = ProcessingJob(
        id=uuid.uuid4(),
        job_type=JobType.DELETE_DOCUMENT,
        priority=JobPriority.INTERACTIVE,
        status=JobStatus.PENDING,
        attempt_count=0,
        max_attempts=3,
        # Scope travels with the job. A worker processes jobs across all users and has
        # no other way to know whose document this is — without it the handler could
        # not build a scoped repository, nor address the cached renders.
        payload={
            "document_id": str(document_id),
            "user_id": str(scope.user_id),
            "knowledge_base_id": str(scope.knowledge_base_id),
            "storage_key": doc.storage_key,
        },
        created_at=now,
        updated_at=now,
    )
    await SqlJobRepository(session).save(job)
    await session.commit()
    return DocumentStatusResponse.model_validate(deleting)
