# ruff: noqa: ARG001
"""Graph resource endpoints — implemented in Phase 12."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.dependencies.scope import get_kb_scope

router = APIRouter(
    prefix="/knowledge-bases/{kb_id}/graph",
    tags=["graph"],
    dependencies=[Depends(get_kb_scope)],
)

_PHASE = "12"


@router.get("", status_code=501)
async def get_graph() -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.get("/entities/{entity_id}", status_code=501)
async def get_graph_entity(entity_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}
