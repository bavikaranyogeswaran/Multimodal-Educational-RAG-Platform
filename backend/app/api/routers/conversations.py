# ruff: noqa: ARG001
"""Conversation and message resource endpoints — implemented in Phase 9."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.dependencies.scope import get_kb_scope

router = APIRouter(
    prefix="/knowledge-bases/{kb_id}/conversations",
    tags=["conversations"],
    dependencies=[Depends(get_kb_scope)],
)

_PHASE = "9"


@router.post("", status_code=501)
async def create_conversation() -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.get("", status_code=501)
async def list_conversations() -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.get("/{conversation_id}", status_code=501)
async def get_conversation(conversation_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.post("/{conversation_id}/stream", status_code=501)
async def stream_response(conversation_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.get("/{conversation_id}/messages", status_code=501)
async def list_messages(conversation_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}
