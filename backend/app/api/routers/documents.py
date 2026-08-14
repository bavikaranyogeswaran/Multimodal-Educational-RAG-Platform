# ruff: noqa: ARG001
"""Document resource endpoints — implemented in Phase 4."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.dependencies.scope import get_kb_scope

router = APIRouter(
    prefix="/knowledge-bases/{kb_id}/documents",
    tags=["documents"],
    dependencies=[Depends(get_kb_scope)],
)

_PHASE = "4"


@router.post("", status_code=501)
async def upload_document() -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.get("/{document_id}", status_code=501)
async def get_document(document_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.get("/{document_id}/status", status_code=501)
async def get_document_status(document_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.delete("/{document_id}", status_code=501)
async def delete_document(document_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}
