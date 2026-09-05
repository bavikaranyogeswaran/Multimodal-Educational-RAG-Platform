"""Pydantic schemas for the study-content API (Phase 15)."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import (
    FlashcardSource,
    QuestionType,
    ReviewRating,
    StudyTaskStatus,
    SummaryType,
)


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


class GenerateSummaryRequest(BaseModel):
    summary_type: SummaryType
    section_ids: list[str] = Field(default_factory=list)
    query: str = Field(
        default="",
        description="Optional topic hint for evidence retrieval",
        max_length=500,
    )


class SummaryResponse(BaseModel):
    id: UUID
    knowledge_base_id: UUID
    summary_type: SummaryType
    section_ids: list[str]
    content: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Quizzes
# ---------------------------------------------------------------------------


class GenerateQuizRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=300)
    n_questions: int = Field(default=5, ge=1, le=20)


class QuizQuestionResponse(BaseModel):
    id: UUID
    question_type: QuestionType
    question: str
    options: list[str] | None
    difficulty: str
    source_chunk_id: UUID | None
    document_id: UUID | None
    page_number: int | None


class QuizResponse(BaseModel):
    id: UUID
    knowledge_base_id: UUID
    topic: str
    questions: list[QuizQuestionResponse]
    created_at: datetime


class SubmitQuizAttemptRequest(BaseModel):
    answers: dict[str, str] = Field(
        description="Map of question_id (string UUID) to submitted answer text"
    )


class QuizAttemptFeedback(BaseModel):
    correct: bool
    correct_answer: str
    explanation: str


class QuizAttemptResponse(BaseModel):
    id: UUID
    quiz_id: UUID
    score: float
    correct_count: int
    total_count: int
    feedback: dict[str, QuizAttemptFeedback]


# ---------------------------------------------------------------------------
# Flashcards
# ---------------------------------------------------------------------------


class GenerateFlashcardsRequest(BaseModel):
    source: FlashcardSource
    query: str = Field(
        default="",
        description="Topic hint for retrieval",
        max_length=500,
    )


class FlashcardResponse(BaseModel):
    id: UUID
    knowledge_base_id: UUID
    front: str
    back: str
    source: FlashcardSource
    source_chunk_id: UUID | None
    document_id: UUID | None
    page_number: int | None
    created_at: datetime


class SubmitFlashcardReviewRequest(BaseModel):
    rating: ReviewRating


class FlashcardReviewResponse(BaseModel):
    id: UUID
    flashcard_id: UUID
    rating: ReviewRating
    reviewed_at: datetime


# ---------------------------------------------------------------------------
# Study plans
# ---------------------------------------------------------------------------


class CreateStudyPlanRequest(BaseModel):
    exam_date: date
    available_hours_per_day: float = Field(gt=0, le=24)
    chapters: list[str] = Field(min_length=1)
    priority_topics: list[str] = Field(default_factory=list)


class StudyTaskResponse(BaseModel):
    id: UUID
    title: str
    description: str
    due_date: date
    chapter_reference: str | None
    hours_allocated: float
    status: StudyTaskStatus


class StudyPlanResponse(BaseModel):
    id: UUID
    knowledge_base_id: UUID
    exam_date: date
    available_hours_per_day: float
    chapters: list[str]
    priority_topics: list[str]
    tasks: list[StudyTaskResponse]
    created_at: datetime


class UpdateStudyTaskRequest(BaseModel):
    status: StudyTaskStatus


# ---------------------------------------------------------------------------
# Learning progress
# ---------------------------------------------------------------------------


class LearningProgressResponse(BaseModel):
    knowledge_base_id: UUID
    topic_mastery: dict[str, float]
    quiz_scores: list[dict]
    flashcard_ratings: dict[str, int]
    completed_chapters: list[str]
    weak_concepts: list[str]
    plan_completion: float
    last_review_date: datetime | None
