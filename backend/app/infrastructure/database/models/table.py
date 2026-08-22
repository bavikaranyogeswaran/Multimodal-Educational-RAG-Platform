"""ORM model for tables lifted off a page as structured objects."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, Float, ForeignKey, Index, Integer, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class DocumentTableModel(Base):
    """One table on one page, with its columns named and its rows aligned to them.

    Headers and units are arrays rather than part of the row payload so a column can be
    searched for directly — "which tables report a density" is a question about the
    headings, not about the values under them.

    Rows are JSONB because they are a nested, rectangular grid of text. A two-dimensional
    array column would express the shape more exactly, but the width is already fixed by
    the row-alignment invariant on the entity, so the extra strictness would buy nothing
    the code is not already guaranteeing.
    """

    __tablename__ = "document_tables"
    __table_args__ = (
        Index("ix_document_tables_document_id", "document_id"),
        Index("ix_document_tables_user_id_kb_id", "user_id", "knowledge_base_id"),
        Index("ix_document_tables_source_element_id", "source_element_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
    )
    # The TABLE element this was read from. Cascades rather than nulls: without the
    # element there is no region on the page, and a table record that cannot be located
    # can be neither cited nor highlighted.
    source_element_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("document_elements.id", ondelete="CASCADE"),
    )
    page_number: Mapped[int] = mapped_column(Integer)

    headers: Mapped[list[str]] = mapped_column(ARRAY(Text()))
    # One entry per column, aligned to headers; NULL where a column carries no unit.
    units: Mapped[list[str | None] | None] = mapped_column(ARRAY(Text()))
    rows: Mapped[list[list[str]]] = mapped_column(JSONB)

    caption: Mapped[str | None] = mapped_column(Text)

    bounding_box_x0: Mapped[float] = mapped_column(Float)
    bounding_box_y0: Mapped[float] = mapped_column(Float)
    bounding_box_x1: Mapped[float] = mapped_column(Float)
    bounding_box_y1: Mapped[float] = mapped_column(Float)

    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
