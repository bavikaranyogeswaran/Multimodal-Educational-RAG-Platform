from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, LargeBinary, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class ProcessingJobModel(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        # Supports the FOR UPDATE SKIP LOCKED claim: filter on status, then order by
        # priority DESC so higher-priority work is claimed first.
        Index("ix_processing_jobs_claim", "status", "priority"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type: Mapped[str] = mapped_column(String(40))
    # Stored as the integer ordinal of JobPriority so ORDER BY priority DESC is native.
    priority: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    attempt_count: Mapped[int] = mapped_column(Integer)
    max_attempts: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, str]] = mapped_column(JSONB)
    # Optional: allows jobs to be queued now but not claimed until a future time.
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Only set while the job is RUNNING; cleared on completion, failure, or cancellation.
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CacheEntryModel(Base):
    """UNLOGGED table for transient cached values.

    UNLOGGED skips WAL entirely — writes are faster, but all rows are discarded on a
    crash or unclean shutdown. That is the correct behavior for a cache: a cold restart
    means cache misses, not data loss. pg_cron sweeps expired rows once per minute.

    The UNLOGGED flag is applied by the migration's raw CREATE UNLOGGED TABLE statement;
    SQLAlchemy has no Table-level kwarg for it so it is not declared in __table_args__.
    """

    __tablename__ = "cache_entries"

    # The key IS the primary identifier — upsert semantics via ON CONFLICT (key) DO UPDATE.
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    # Arbitrary bytes: covers page renders, serialized embeddings, JSON blobs, and more.
    value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # NULL means the entry never expires; pg_cron only deletes rows where this is set.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
