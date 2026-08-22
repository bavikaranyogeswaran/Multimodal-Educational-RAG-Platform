"""ORM model for figures, charts and diagrams detected on a page."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, Float, ForeignKey, Index, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class DocumentFigureModel(Base):
    """One figure, chart or diagram on one page.

    All three visual kinds share this table, discriminated by the `kind` column.
    Chart-specific fields (axis labels, chart type) are null for figures and
    diagrams; diagram-specific fields are null for figures and charts. Neither
    set carries a NOT NULL constraint, because at detection time every field that
    requires looking at the image is absent, and the schema exists before the
    work that fills it does.
    """

    __tablename__ = "document_figures"
    __table_args__ = (
        Index("ix_document_figures_document_id", "document_id"),
        Index("ix_document_figures_user_id_kb_id", "user_id", "knowledge_base_id"),
        Index("ix_document_figures_source_element_id", "source_element_id"),
        # Looking up a figure by its number is always a scoped lookup — queries
        # always filter by user and knowledge base first.
        Index("ix_document_figures_scope_number", "user_id", "knowledge_base_id", "number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
    )
    # Cascades rather than nulls: without its element there is no region on the
    # page, and a figure record that cannot be located can be neither cited nor
    # highlighted.
    source_element_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("document_elements.id", ondelete="CASCADE"),
    )
    page_number: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text)

    bounding_box_x0: Mapped[float] = mapped_column(Float)
    bounding_box_y0: Mapped[float] = mapped_column(Float)
    bounding_box_x1: Mapped[float] = mapped_column(Float)
    bounding_box_y1: Mapped[float] = mapped_column(Float)

    caption: Mapped[str | None] = mapped_column(Text)
    # The number the document printed, as written: "3.2", "A.1", "5b". Text
    # because none of these are numeric and "3.2" and "3-2" are different.
    number: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # R2 storage key for the cropped image. Set during ingestion (step 6.5); null
    # on records created before that step ran, or when the page failed to render.
    crop_key: Mapped[str | None] = mapped_column(Text)

    # Populated in Phase 6.7 after the crop is processed.
    ocr_text: Mapped[str | None] = mapped_column(Text)
    surrounding_text: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)

    # Chart-specific (FR-VIS-03). Null for FIGURE and DIAGRAM kinds.
    title: Mapped[str | None] = mapped_column(Text)
    chart_type: Mapped[str | None] = mapped_column(Text)
    x_axis_label: Mapped[str | None] = mapped_column(Text)
    y_axis_label: Mapped[str | None] = mapped_column(Text)
    units_label: Mapped[str | None] = mapped_column(Text)
    legend: Mapped[str | None] = mapped_column(Text)
    data_labels: Mapped[str | None] = mapped_column(Text)
    visible_trend: Mapped[str | None] = mapped_column(Text)

    # Diagram-specific (FR-VIS-04). Null/empty for FIGURE and CHART kinds.
    diagram_labels: Mapped[list[str] | None] = mapped_column(ARRAY(Text()))
    components: Mapped[list[str] | None] = mapped_column(ARRAY(Text()))
    arrows: Mapped[list[str] | None] = mapped_column(ARRAY(Text()))
    visible_relationships: Mapped[list[str] | None] = mapped_column(ARRAY(Text()))
