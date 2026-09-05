"""SQLAlchemy repositories for study-content entities."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.domain.enums import (
    FlashcardSource,
    QuestionType,
    ReviewRating,
    StudyTaskStatus,
    SummaryType,
)
from app.domain.scope import ScopeContext
from app.domain.study.entities import (
    Flashcard,
    FlashcardReview,
    Quiz,
    QuizAttempt,
    QuizQuestion,
    StudyPlan,
    StudySummary,
    StudyTask,
)
from app.infrastructure.database.models.study import (
    FlashcardModel,
    FlashcardReviewModel,
    QuizAttemptModel,
    QuizModel,
    QuizQuestionModel,
    StudyPlanModel,
    StudySummaryModel,
    StudyTaskModel,
)
from app.infrastructure.database.repository import ScopedRepository


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


class SqlStudySummaryRepository(ScopedRepository):
    async def save(self, scope: ScopeContext, summary: StudySummary) -> None:
        self._require_scope(scope)
        await self._session.merge(_summary_to_model(summary))

    async def list(self, scope: ScopeContext) -> Sequence[StudySummary]:
        self._require_scope(scope)
        stmt = select(StudySummaryModel).where(self._scope_filter(StudySummaryModel))
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_summary_to_entity(r) for r in rows]


# ---------------------------------------------------------------------------
# Quizzes
# ---------------------------------------------------------------------------


class SqlQuizRepository(ScopedRepository):
    async def save(self, scope: ScopeContext, quiz: Quiz) -> None:
        self._require_scope(scope)
        await self._session.merge(_quiz_to_model(quiz))
        for q in quiz.questions:
            await self._session.merge(_question_to_model(q))

    async def get(self, scope: ScopeContext, quiz_id: uuid.UUID) -> Quiz | None:
        self._require_scope(scope)
        row = (
            await self._session.execute(
                select(QuizModel).where(
                    QuizModel.id == quiz_id, self._scope_filter(QuizModel)
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        questions = (
            await self._session.execute(
                select(QuizQuestionModel).where(QuizQuestionModel.quiz_id == quiz_id)
            )
        ).scalars().all()
        return _quiz_to_entity(row, list(questions))

    async def save_attempt(self, scope: ScopeContext, attempt: QuizAttempt) -> None:
        self._require_scope(scope)
        await self._session.merge(_attempt_to_model(attempt))

    async def list_attempts(
        self, scope: ScopeContext, quiz_id: uuid.UUID
    ) -> Sequence[QuizAttempt]:
        self._require_scope(scope)
        stmt = (
            select(QuizAttemptModel)
            .where(
                QuizAttemptModel.quiz_id == quiz_id,
                self._scope_filter(QuizAttemptModel),
            )
            .order_by(QuizAttemptModel.created_at)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_attempt_to_entity(r) for r in rows]

    async def list_all_attempts(self, scope: ScopeContext) -> Sequence[QuizAttempt]:
        self._require_scope(scope)
        stmt = (
            select(QuizAttemptModel)
            .where(self._scope_filter(QuizAttemptModel))
            .order_by(QuizAttemptModel.created_at)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_attempt_to_entity(r) for r in rows]


# ---------------------------------------------------------------------------
# Flashcards
# ---------------------------------------------------------------------------


class SqlFlashcardRepository(ScopedRepository):
    async def save_batch(self, scope: ScopeContext, cards: Sequence[Flashcard]) -> None:
        self._require_scope(scope)
        for card in cards:
            await self._session.merge(_flashcard_to_model(card))

    async def list(self, scope: ScopeContext) -> Sequence[Flashcard]:
        self._require_scope(scope)
        stmt = select(FlashcardModel).where(self._scope_filter(FlashcardModel))
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_flashcard_to_entity(r) for r in rows]

    async def save_review(self, scope: ScopeContext, review: FlashcardReview) -> None:
        self._require_scope(scope)
        await self._session.merge(_review_to_model(review))

    async def list_reviews(self, scope: ScopeContext) -> Sequence[FlashcardReview]:
        self._require_scope(scope)
        stmt = (
            select(FlashcardReviewModel)
            .where(self._scope_filter(FlashcardReviewModel))
            .order_by(FlashcardReviewModel.reviewed_at)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_review_to_entity(r) for r in rows]

    async def last_review_date(self, scope: ScopeContext) -> datetime | None:
        self._require_scope(scope)
        from sqlalchemy import func
        stmt = select(func.max(FlashcardReviewModel.reviewed_at)).where(
            self._scope_filter(FlashcardReviewModel)
        )
        result = (await self._session.execute(stmt)).scalar_one_or_none()
        return result


# ---------------------------------------------------------------------------
# Study plans
# ---------------------------------------------------------------------------


class SqlStudyPlanRepository(ScopedRepository):
    async def save(self, scope: ScopeContext, plan: StudyPlan) -> None:
        self._require_scope(scope)
        await self._session.merge(_plan_to_model(plan))
        for task in plan.tasks:
            await self._session.merge(_task_to_model(task))

    async def list(self, scope: ScopeContext) -> Sequence[StudyPlan]:
        self._require_scope(scope)
        rows = (
            await self._session.execute(
                select(StudyPlanModel).where(self._scope_filter(StudyPlanModel))
            )
        ).scalars().all()
        plans: list[StudyPlan] = []
        for row in rows:
            tasks = (
                await self._session.execute(
                    select(StudyTaskModel).where(
                        StudyTaskModel.plan_id == row.id
                    ).order_by(StudyTaskModel.due_date)
                )
            ).scalars().all()
            plans.append(_plan_to_entity(row, list(tasks)))
        return plans

    async def update_task_status(
        self,
        scope: ScopeContext,
        plan_id: uuid.UUID,
        task_id: uuid.UUID,
        status: StudyTaskStatus,
    ) -> None:
        self._require_scope(scope)
        await self._session.execute(
            update(StudyTaskModel)
            .where(
                StudyTaskModel.id == task_id,
                StudyTaskModel.plan_id == plan_id,
            )
            .values(status=status.value)
        )

    async def list_all_tasks(self, scope: ScopeContext) -> Sequence[StudyTask]:
        self._require_scope(scope)
        stmt = (
            select(StudyTaskModel)
            .join(StudyPlanModel, StudyTaskModel.plan_id == StudyPlanModel.id)
            .where(self._scope_filter(StudyPlanModel))
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_task_to_entity(r) for r in rows]


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------


def _summary_to_model(e: StudySummary) -> StudySummaryModel:
    m = StudySummaryModel()
    m.id = e.id
    m.knowledge_base_id = e.kb_id
    m.user_id = e.user_id
    m.summary_type = e.summary_type.value
    m.section_ids = list(e.section_ids)
    m.content = e.content
    m.created_at = e.created_at
    return m


def _summary_to_entity(m: StudySummaryModel) -> StudySummary:
    return StudySummary(
        id=m.id,
        kb_id=m.knowledge_base_id,
        user_id=m.user_id,
        summary_type=SummaryType(m.summary_type),
        section_ids=tuple(m.section_ids),
        content=m.content,
        created_at=m.created_at,
    )


def _quiz_to_model(e: Quiz) -> QuizModel:
    m = QuizModel()
    m.id = e.id
    m.knowledge_base_id = e.kb_id
    m.user_id = e.user_id
    m.topic = e.topic
    m.created_at = e.created_at
    return m


def _question_to_model(e: QuizQuestion) -> QuizQuestionModel:
    m = QuizQuestionModel()
    m.id = e.id
    m.quiz_id = e.quiz_id
    m.question_type = e.question_type.value
    m.question = e.question
    m.options = list(e.options) if e.options else None
    m.correct_answer = e.correct_answer
    m.explanation = e.explanation
    m.difficulty = e.difficulty
    m.source_chunk_id = e.source_chunk_id
    m.document_id = e.document_id
    m.page_number = e.page_number
    return m


def _quiz_to_entity(
    m: QuizModel, question_rows: list[QuizQuestionModel]
) -> Quiz:
    questions = tuple(_question_to_entity(q) for q in question_rows)
    return Quiz(
        id=m.id,
        kb_id=m.knowledge_base_id,
        user_id=m.user_id,
        topic=m.topic,
        questions=questions,
        created_at=m.created_at,
    )


def _question_to_entity(m: QuizQuestionModel) -> QuizQuestion:
    return QuizQuestion(
        id=m.id,
        quiz_id=m.quiz_id,
        question_type=QuestionType(m.question_type),
        question=m.question,
        options=tuple(m.options) if m.options else None,
        correct_answer=m.correct_answer,
        explanation=m.explanation,
        difficulty=m.difficulty,
        source_chunk_id=m.source_chunk_id,
        document_id=m.document_id,
        page_number=m.page_number,
    )


def _attempt_to_model(e: QuizAttempt) -> QuizAttemptModel:
    m = QuizAttemptModel()
    m.id = e.id
    m.quiz_id = e.quiz_id
    m.knowledge_base_id = e.kb_id
    m.user_id = e.user_id
    m.answers = e.answers
    m.score = e.score
    m.correct_count = e.correct_count
    m.total_count = e.total_count
    m.incorrect_question_ids = [str(qid) for qid in e.incorrect_question_ids]
    m.created_at = e.created_at
    return m


def _attempt_to_entity(m: QuizAttemptModel) -> QuizAttempt:
    return QuizAttempt(
        id=m.id,
        quiz_id=m.quiz_id,
        kb_id=m.knowledge_base_id,
        user_id=m.user_id,
        answers=m.answers,
        score=m.score,
        correct_count=m.correct_count,
        total_count=m.total_count,
        incorrect_question_ids=tuple(
            uuid.UUID(qid) for qid in m.incorrect_question_ids
        ),
        created_at=m.created_at,
    )


def _flashcard_to_model(e: Flashcard) -> FlashcardModel:
    m = FlashcardModel()
    m.id = e.id
    m.knowledge_base_id = e.kb_id
    m.user_id = e.user_id
    m.front = e.front
    m.back = e.back
    m.source = e.source.value
    m.source_chunk_id = e.source_chunk_id
    m.document_id = e.document_id
    m.page_number = e.page_number
    m.created_at = e.created_at
    return m


def _flashcard_to_entity(m: FlashcardModel) -> Flashcard:
    return Flashcard(
        id=m.id,
        kb_id=m.knowledge_base_id,
        user_id=m.user_id,
        front=m.front,
        back=m.back,
        source=FlashcardSource(m.source),
        source_chunk_id=m.source_chunk_id,
        document_id=m.document_id,
        page_number=m.page_number,
        created_at=m.created_at,
    )


def _review_to_model(e: FlashcardReview) -> FlashcardReviewModel:
    m = FlashcardReviewModel()
    m.id = e.id
    m.flashcard_id = e.flashcard_id
    m.knowledge_base_id = e.kb_id
    m.user_id = e.user_id
    m.rating = e.rating.value
    m.reviewed_at = e.reviewed_at
    return m


def _review_to_entity(m: FlashcardReviewModel) -> FlashcardReview:
    return FlashcardReview(
        id=m.id,
        flashcard_id=m.flashcard_id,
        kb_id=m.knowledge_base_id,
        user_id=m.user_id,
        rating=ReviewRating(m.rating),
        reviewed_at=m.reviewed_at,
    )


def _plan_to_model(e: StudyPlan) -> StudyPlanModel:
    m = StudyPlanModel()
    m.id = e.id
    m.knowledge_base_id = e.kb_id
    m.user_id = e.user_id
    m.exam_date = e.exam_date
    m.available_hours_per_day = e.available_hours_per_day
    m.chapters = list(e.chapters)
    m.priority_topics = list(e.priority_topics)
    m.created_at = e.created_at
    return m


def _task_to_model(e: StudyTask) -> StudyTaskModel:
    m = StudyTaskModel()
    m.id = e.id
    m.plan_id = e.plan_id
    m.title = e.title
    m.description = e.description
    m.due_date = e.due_date
    m.chapter_reference = e.chapter_reference
    m.hours_allocated = e.hours_allocated
    m.status = e.status.value
    return m


def _plan_to_entity(m: StudyPlanModel, task_rows: list[StudyTaskModel]) -> StudyPlan:
    return StudyPlan(
        id=m.id,
        kb_id=m.knowledge_base_id,
        user_id=m.user_id,
        exam_date=m.exam_date,
        available_hours_per_day=m.available_hours_per_day,
        chapters=tuple(m.chapters),
        priority_topics=tuple(m.priority_topics),
        tasks=tuple(_task_to_entity(t) for t in task_rows),
        created_at=m.created_at,
    )


def _task_to_entity(m: StudyTaskModel) -> StudyTask:
    return StudyTask(
        id=m.id,
        plan_id=m.plan_id,
        title=m.title,
        description=m.description,
        due_date=m.due_date,
        chapter_reference=m.chapter_reference,
        hours_allocated=m.hours_allocated,
        status=StudyTaskStatus(m.status),
    )
