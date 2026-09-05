"""SQLAlchemy ORM models for Phase 15 study-content tables."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class StudySummaryModel(Base):
    __tablename__ = "study_summaries"
    __table_args__ = (
        Index("ix_study_summaries_user_kb", "user_id", "knowledge_base_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    summary_type: Mapped[str] = mapped_column(String(30))
    section_ids: Mapped[list] = mapped_column(JSONB, server_default="[]")
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QuizModel(Base):
    __tablename__ = "quizzes"
    __table_args__ = (
        Index("ix_quizzes_user_kb", "user_id", "knowledge_base_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    topic: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QuizQuestionModel(Base):
    __tablename__ = "quiz_questions"
    __table_args__ = (Index("ix_quiz_questions_quiz_id", "quiz_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    quiz_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("quizzes.id", ondelete="CASCADE")
    )
    question_type: Mapped[str] = mapped_column(String(30))
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    correct_answer: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(String(10))
    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)


class QuizAttemptModel(Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = (
        Index("ix_quiz_attempts_quiz_id", "quiz_id"),
        Index("ix_quiz_attempts_user_kb", "user_id", "knowledge_base_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    quiz_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("quizzes.id", ondelete="CASCADE")
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    answers: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    score: Mapped[float] = mapped_column(Float)
    correct_count: Mapped[int] = mapped_column(Integer)
    total_count: Mapped[int] = mapped_column(Integer)
    incorrect_question_ids: Mapped[list] = mapped_column(JSONB, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FlashcardModel(Base):
    __tablename__ = "flashcards"
    __table_args__ = (
        Index("ix_flashcards_user_kb", "user_id", "knowledge_base_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20))
    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FlashcardReviewModel(Base):
    __tablename__ = "flashcard_reviews"
    __table_args__ = (
        Index("ix_flashcard_reviews_flashcard_id", "flashcard_id"),
        Index("ix_flashcard_reviews_user_kb", "user_id", "knowledge_base_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    flashcard_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("flashcards.id", ondelete="CASCADE")
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    rating: Mapped[str] = mapped_column(String(10))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StudyPlanModel(Base):
    __tablename__ = "study_plans"
    __table_args__ = (
        Index("ix_study_plans_user_kb", "user_id", "knowledge_base_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    exam_date: Mapped[date] = mapped_column(Date)
    available_hours_per_day: Mapped[float] = mapped_column(Float)
    chapters: Mapped[list] = mapped_column(JSONB, server_default="[]")
    priority_topics: Mapped[list] = mapped_column(JSONB, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StudyTaskModel(Base):
    __tablename__ = "study_tasks"
    __table_args__ = (Index("ix_study_tasks_plan_id", "plan_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("study_plans.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    due_date: Mapped[date] = mapped_column(Date)
    chapter_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    hours_allocated: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(15), server_default="PENDING")
