from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class ModelInvocationModel(Base):
    """One row per completed model inference call.

    Streaming calls are not recorded here because end-to-end latency is not a single
    number on that path. Everything else — text generation, image generation, reraise
    after fallback — produces one row.
    """

    __tablename__ = "model_invocations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[str | None] = mapped_column(Text)
    task: Mapped[str] = mapped_column(String(50))
    provider: Mapped[str] = mapped_column(String(100))
    model_id: Mapped[str] = mapped_column(String(200))
    prompt_tokens: Mapped[int] = mapped_column(Integer)
    completion_tokens: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    used_fallback: Mapped[bool] = mapped_column(Boolean, server_default="false")
    cache_hit: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
