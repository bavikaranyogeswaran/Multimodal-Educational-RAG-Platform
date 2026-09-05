"""Use case: record a flashcard review with a spaced-repetition rating."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain.enums import ReviewRating
from app.domain.scope import ScopeContext
from app.domain.study.entities import FlashcardReview


@dataclass(frozen=True)
class SubmitFlashcardReviewCommand:
    scope: ScopeContext
    flashcard_id: uuid.UUID
    rating: ReviewRating


@dataclass(frozen=True)
class SubmitFlashcardReviewResult:
    review: FlashcardReview


class SubmitFlashcardReviewUseCase:
    def __init__(self, *, flashcard_repo: object) -> None:  # SqlFlashcardRepository
        self._repo = flashcard_repo

    async def execute(
        self, command: SubmitFlashcardReviewCommand, session: object
    ) -> SubmitFlashcardReviewResult:
        review = FlashcardReview(
            id=uuid.uuid4(),
            flashcard_id=command.flashcard_id,
            kb_id=command.scope.knowledge_base_id,
            user_id=command.scope.user_id,
            rating=command.rating,
            reviewed_at=datetime.now(UTC),
        )
        await self._repo.save_review(command.scope, review)
        return SubmitFlashcardReviewResult(review=review)
