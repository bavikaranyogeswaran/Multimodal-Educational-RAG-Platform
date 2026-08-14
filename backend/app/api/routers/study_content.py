# ruff: noqa: ARG001
"""Study content resource endpoints (summaries, quizzes, flashcards, study plans, progress)
— implemented in Phase 15."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.dependencies.scope import get_kb_scope

router = APIRouter(
    prefix="/knowledge-bases/{kb_id}",
    tags=["study-content"],
    dependencies=[Depends(get_kb_scope)],
)

_PHASE = "15"


@router.post("/summaries", status_code=501)
async def generate_summary() -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.get("/summaries", status_code=501)
async def list_summaries() -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.post("/quizzes", status_code=501)
async def generate_quiz() -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.get("/quizzes/{quiz_id}", status_code=501)
async def get_quiz(quiz_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.post("/quizzes/{quiz_id}/attempts", status_code=501)
async def submit_quiz_attempt(quiz_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.post("/flashcards", status_code=501)
async def generate_flashcards() -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.get("/flashcards", status_code=501)
async def list_flashcards() -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.post("/flashcards/{card_id}/reviews", status_code=501)
async def submit_flashcard_review(card_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.post("/study-plans", status_code=501)
async def create_study_plan() -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.get("/study-plans", status_code=501)
async def list_study_plans() -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.patch("/study-plans/{plan_id}/tasks/{task_id}", status_code=501)
async def update_study_task(plan_id: uuid.UUID, task_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.get("/progress", status_code=501)
async def get_progress() -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}
