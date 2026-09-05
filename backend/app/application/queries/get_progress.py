"""Query: compute and return structured learning progress for a knowledge base.

Learning progress is structured data read from multiple tables — it is never
a prose conversation summary (FR-PRG-02). All computation is done in Python
from the raw repository data.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.domain.enums import ReviewRating
from app.domain.scope import ScopeContext
from app.domain.study.entities import LearningProgress


@dataclass(frozen=True)
class GetProgressQuery:
    scope: ScopeContext


class GetProgressUseCase:
    def __init__(
        self,
        *,
        quiz_repo: object,       # SqlQuizRepository
        flashcard_repo: object,  # SqlFlashcardRepository
        plan_repo: object,       # SqlStudyPlanRepository
    ) -> None:
        self._quiz_repo = quiz_repo
        self._flashcard_repo = flashcard_repo
        self._plan_repo = plan_repo

    async def execute(self, query: GetProgressQuery) -> LearningProgress:
        scope = query.scope

        # Quiz performance — per attempt, score, date.
        attempts = list(await self._quiz_repo.list_all_attempts(scope))
        quiz_scores: list[dict] = [
            {
                "quiz_id": str(a.quiz_id),
                "score": a.score,
                "correct": a.correct_count,
                "total": a.total_count,
                "date": a.created_at.isoformat(),
            }
            for a in attempts
        ]

        # Topic mastery — group by quiz (topic is on the quiz not the attempt).
        # We treat each quiz as a topic proxy: mean score across all attempts for that quiz.
        quiz_scores_by_quiz: dict[str, list[float]] = {}
        for a in attempts:
            qid = str(a.quiz_id)
            quiz_scores_by_quiz.setdefault(qid, []).append(a.score)
        topic_mastery: dict[str, float] = {
            qid: sum(scores) / len(scores)
            for qid, scores in quiz_scores_by_quiz.items()
        }

        # Weak concepts — quiz IDs whose mean score is below 0.6.
        weak_concepts = tuple(
            qid for qid, mastery in topic_mastery.items() if mastery < 0.6
        )

        # Flashcard rating distribution.
        reviews = list(await self._flashcard_repo.list_reviews(scope))
        rating_counts: Counter[str] = Counter(r.rating.value for r in reviews)
        flashcard_ratings: dict[str, int] = dict(rating_counts)

        # Last review date.
        last_review = await self._flashcard_repo.last_review_date(scope)

        # Study plan completion.
        tasks = list(await self._plan_repo.list_all_tasks(scope))
        total_tasks = len(tasks)
        completed_tasks = sum(1 for t in tasks if t.status.value == "COMPLETED")
        plan_completion = completed_tasks / total_tasks if total_tasks else 0.0

        # Completed chapters — tasks marked COMPLETED with a chapter_reference.
        completed_chapters = tuple(
            t.chapter_reference
            for t in tasks
            if t.status.value == "COMPLETED" and t.chapter_reference
        )

        return LearningProgress(
            kb_id=scope.knowledge_base_id,
            user_id=scope.user_id,
            topic_mastery=topic_mastery,
            quiz_scores=tuple(quiz_scores),
            flashcard_ratings=flashcard_ratings,
            completed_chapters=completed_chapters,
            weak_concepts=weak_concepts,
            plan_completion=plan_completion,
            last_review_date=last_review,
        )
