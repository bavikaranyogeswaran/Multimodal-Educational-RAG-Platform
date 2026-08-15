# ruff: noqa: ARG001
"""Document resource endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.container import get_container
from app.api.dependencies.scope import get_kb_scope
from app.api.schemas.document import DocumentUploadResponse
from app.application.commands.upload_document import (
    UploadDocumentCommand,
    UploadDocumentUseCase,
)
from app.configuration.container import Container
from app.configuration.settings import Settings, get_settings
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.document import SqlDocumentRepository
from app.infrastructure.database.repositories.job import SqlJobRepository
from app.infrastructure.database.session import get_session

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


@router.get("/{document_id}", status_code=501)
async def get_document(document_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.get("/{document_id}/status", status_code=501)
async def get_document_status(document_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.delete("/{document_id}", status_code=501)
async def delete_document(document_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}
