# ruff: noqa: ARG001
"""Document resource endpoints."""

from __future__ import annotations

import io
import uuid
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
)
from app.application.commands.upload_document import (
    UploadDocumentCommand,
    UploadDocumentUseCase,
)
from app.configuration.container import Container
from app.configuration.settings import Settings, get_settings
from app.domain.errors import UploadValidationError
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.document import SqlDocumentRepository
from app.infrastructure.database.repositories.job import SqlJobRepository
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

_PHASE = "4"


@router.post("", status_code=201)
async def upload_document(
    file: UploadFile,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
    container: Annotated[Container, Depends(get_container)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentUploadResponse:
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


@router.delete("/{document_id}", status_code=501)
async def delete_document(document_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}
