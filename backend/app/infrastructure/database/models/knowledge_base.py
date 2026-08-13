from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class KnowledgeBaseModel(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (Index("ix_knowledge_bases_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(Text)
    learning_goal: Mapped[str | None] = mapped_column(Text)
    preferred_language: Mapped[str] = mapped_column(String(10), server_default="en")
    explanation_level: Mapped[str] = mapped_column(String(20), server_default="INTERMEDIATE")
    exam_date: Mapped[date | None] = mapped_column(Date)
    graph_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    active_index_version: Mapped[int] = mapped_column(Integer, server_default="1")
    active_graph_version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
