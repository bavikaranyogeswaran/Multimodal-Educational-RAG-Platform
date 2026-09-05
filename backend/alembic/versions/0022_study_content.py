"""Add study-content tables: summaries, quizzes, flashcards, study plans and progress.

Covers Phase 15 (§46, §47): study summaries, quiz questions and attempts,
flashcards and reviews, study plans and tasks. Learning progress is computed
from these tables at query time — no separate table needed.

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "study_summaries",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True),
                  sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("summary_type", sa.String(30), nullable=False),
        sa.Column("section_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_study_summaries_user_kb", "study_summaries",
                    ["user_id", "knowledge_base_id"])

    op.create_table(
        "quizzes",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True),
                  sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("topic", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quizzes_user_kb", "quizzes", ["user_id", "knowledge_base_id"])

    op.create_table(
        "quiz_questions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("quiz_id", sa.Uuid(as_uuid=True),
                  sa.ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_type", sa.String(30), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("options", JSONB, nullable=True),
        sa.Column("correct_answer", sa.Text, nullable=False),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column("difficulty", sa.String(10), nullable=False),
        sa.Column("source_chunk_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("page_number", sa.Integer, nullable=True),
    )
    op.create_index("ix_quiz_questions_quiz_id", "quiz_questions", ["quiz_id"])

    op.create_table(
        "quiz_attempts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("quiz_id", sa.Uuid(as_uuid=True),
                  sa.ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("answers", JSONB, nullable=False, server_default="{}"),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("correct_count", sa.Integer, nullable=False),
        sa.Column("total_count", sa.Integer, nullable=False),
        sa.Column("incorrect_question_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quiz_attempts_quiz_id", "quiz_attempts", ["quiz_id"])
    op.create_index("ix_quiz_attempts_user_kb", "quiz_attempts",
                    ["user_id", "knowledge_base_id"])

    op.create_table(
        "flashcards",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True),
                  sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("front", sa.Text, nullable=False),
        sa.Column("back", sa.Text, nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("source_chunk_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("page_number", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_flashcards_user_kb", "flashcards", ["user_id", "knowledge_base_id"])

    op.create_table(
        "flashcard_reviews",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("flashcard_id", sa.Uuid(as_uuid=True),
                  sa.ForeignKey("flashcards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("rating", sa.String(10), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_flashcard_reviews_flashcard_id", "flashcard_reviews", ["flashcard_id"])
    op.create_index("ix_flashcard_reviews_user_kb", "flashcard_reviews",
                    ["user_id", "knowledge_base_id"])

    op.create_table(
        "study_plans",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True),
                  sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("exam_date", sa.Date, nullable=False),
        sa.Column("available_hours_per_day", sa.Float, nullable=False),
        sa.Column("chapters", JSONB, nullable=False, server_default="[]"),
        sa.Column("priority_topics", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_study_plans_user_kb", "study_plans", ["user_id", "knowledge_base_id"])

    op.create_table(
        "study_tasks",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("plan_id", sa.Uuid(as_uuid=True),
                  sa.ForeignKey("study_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("chapter_reference", sa.Text, nullable=True),
        sa.Column("hours_allocated", sa.Float, nullable=False),
        sa.Column("status", sa.String(15), nullable=False, server_default="PENDING"),
    )
    op.create_index("ix_study_tasks_plan_id", "study_tasks", ["plan_id"])


def downgrade() -> None:
    op.drop_index("ix_study_tasks_plan_id", table_name="study_tasks")
    op.drop_table("study_tasks")
    op.drop_index("ix_study_plans_user_kb", table_name="study_plans")
    op.drop_table("study_plans")
    op.drop_index("ix_flashcard_reviews_user_kb", table_name="flashcard_reviews")
    op.drop_index("ix_flashcard_reviews_flashcard_id", table_name="flashcard_reviews")
    op.drop_table("flashcard_reviews")
    op.drop_index("ix_flashcards_user_kb", table_name="flashcards")
    op.drop_table("flashcards")
    op.drop_index("ix_quiz_attempts_user_kb", table_name="quiz_attempts")
    op.drop_index("ix_quiz_attempts_quiz_id", table_name="quiz_attempts")
    op.drop_table("quiz_attempts")
    op.drop_index("ix_quiz_questions_quiz_id", table_name="quiz_questions")
    op.drop_table("quiz_questions")
    op.drop_index("ix_quizzes_user_kb", table_name="quizzes")
    op.drop_table("quizzes")
    op.drop_index("ix_study_summaries_user_kb", table_name="study_summaries")
    op.drop_table("study_summaries")
