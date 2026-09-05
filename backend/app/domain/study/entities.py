"""Domain entities for study-content generation and learning progress."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from app.domain.enums import (
    FlashcardSource,
    QuestionType,
    ReviewRating,
    StudyTaskStatus,
    SummaryType,
)


@dataclass(frozen=True)
class StudySummary:
    id: uuid.UUID
    kb_id: uuid.UUID
    user_id: uuid.UUID
    summary_type: SummaryType
    section_ids: tuple[str, ...]
    content: str
    created_at: datetime


@dataclass(frozen=True)
class QuizQuestion:
    id: uuid.UUID
    quiz_id: uuid.UUID
    question_type: QuestionType
    question: str
    options: tuple[str, ...] | None
    correct_answer: str
    explanation: str
    difficulty: str
    source_chunk_id: uuid.UUID | None
    document_id: uuid.UUID | None
    page_number: int | None


@dataclass(frozen=True)
class Quiz:
    id: uuid.UUID
    kb_id: uuid.UUID
    user_id: uuid.UUID
    topic: str
    questions: tuple[QuizQuestion, ...]
    created_at: datetime


@dataclass(frozen=True)
class QuizAttempt:
    id: uuid.UUID
    quiz_id: uuid.UUID
    kb_id: uuid.UUID
    user_id: uuid.UUID
    answers: dict[str, str]  # str(question_id) -> answer text
    score: float
    correct_count: int
    total_count: int
    incorrect_question_ids: tuple[uuid.UUID, ...]
    created_at: datetime


@dataclass(frozen=True)
class Flashcard:
    id: uuid.UUID
    kb_id: uuid.UUID
    user_id: uuid.UUID
    front: str
    back: str
    source: FlashcardSource
    source_chunk_id: uuid.UUID | None
    document_id: uuid.UUID | None
    page_number: int | None
    created_at: datetime


@dataclass(frozen=True)
class FlashcardReview:
    id: uuid.UUID
    flashcard_id: uuid.UUID
    kb_id: uuid.UUID
    user_id: uuid.UUID
    rating: ReviewRating
    reviewed_at: datetime


@dataclass(frozen=True)
class StudyTask:
    id: uuid.UUID
    plan_id: uuid.UUID
    title: str
    description: str
    due_date: date
    chapter_reference: str | None
    hours_allocated: float
    status: StudyTaskStatus


@dataclass(frozen=True)
class StudyPlan:
    id: uuid.UUID
    kb_id: uuid.UUID
    user_id: uuid.UUID
    exam_date: date
    available_hours_per_day: float
    chapters: tuple[str, ...]
    priority_topics: tuple[str, ...]
    tasks: tuple[StudyTask, ...]
    created_at: datetime


@dataclass(frozen=True)
class LearningProgress:
    kb_id: uuid.UUID
    user_id: uuid.UUID
    topic_mastery: dict[str, float]
    quiz_scores: tuple[dict, ...]
    flashcard_ratings: dict[str, int]
    completed_chapters: tuple[str, ...]
    weak_concepts: tuple[str, ...]
    plan_completion: float
    last_review_date: datetime | None
