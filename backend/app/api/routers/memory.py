# ruff: noqa: ARG001
"""Memory resource endpoints — implemented in Phase 14."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.dependencies.scope import get_kb_scope

router = APIRouter(
    prefix="/knowledge-bases/{kb_id}/memory",
    tags=["memory"],
    dependencies=[Depends(get_kb_scope)],
)

_PHASE = "14"


@router.get("", status_code=501)
async def list_memory() -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.patch("/{memory_id}", status_code=501)
async def update_memory(memory_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.delete("/{memory_id}", status_code=501)
async def delete_memory(memory_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}
