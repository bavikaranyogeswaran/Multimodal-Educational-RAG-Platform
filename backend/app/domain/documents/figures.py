"""A visual object on a page: a figure, chart or diagram.

Every visual starts as a region on a page. At detection time, pdfplumber
identifies it as an image; at that point the only certain things are where it
sits, which element record it corresponds to, and what caption the document gave
it. Everything else — the chart axes, the diagram labels, the factual description
of what it shows — waits on a model that can actually see the image.

This module records what is known at detection time and provides the schema for
what will be known after Phase 6.7 runs. The description field is explicitly
nullable and typed as a derived value, not a primary source: a model read an
image, not the underlying data, and its description should be weighted as
interpretation rather than measurement.

Three kinds share one entity type because they share almost all of their schema.
A chart has axis labels and chart type where a diagram has component labels and
arrows, but both have a caption, a bounding box, OCR text and a derived
description. Using a single entity avoids repeated fields across nearly-identical
types while a `kind` discriminator tells the rest of the system what it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import ElementType
from app.domain.errors import InvariantViolationError
from app.domain.invariants import require_positive, require_timezone_aware, require_within
from app.domain.scope import ScopeContext
from app.domain.values import BoundingBox, UntrustedText

# Element types that map to a figure record. Anything else is a programming error.
_VISUAL_KINDS: frozenset[ElementType] = frozenset(
    {ElementType.FIGURE, ElementType.CHART, ElementType.DIAGRAM}
)


@dataclass(frozen=True, slots=True)
class DocumentFigure:
    """A figure, chart or diagram on one page.

    All fields populated at detection time are required; fields that require a
    model to read the image are nullable and absent until Phase 6.7 fills them.
    Chart-specific fields (axis labels, chart type) are always null for FIGURE
    and DIAGRAM kinds; diagram-specific fields are null for FIGURE and CHART.
    Both sets are defined here rather than in subclasses because domain entities
    are plain frozen dataclasses and the spec's schema for all three types shares
    more than it differs.
    """

    id: UUID
    user_id: UUID
    knowledge_base_id: UUID
    document_id: UUID
    source_element_id: UUID
    page_number: int
    # FIGURE, CHART, or DIAGRAM. Detected as FIGURE at parse time; upgraded to
    # CHART or DIAGRAM by Phase 6.7 after image classification.
    kind: ElementType
    bounding_box: BoundingBox
    created_at: datetime

    # Document-supplied label and number. Caption is kept as written; number is
    # extracted from it separately so "Figure 3.2" resolves to this record.
    caption: UntrustedText | None = None
    number: str | None = None

    # Detection quality. A region of background imagery can look like a figure
    # to a layout analyser; confidence lets downstream code weigh detections.
    confidence: float | None = None

    # Populated in Phase 6.7 after OCR runs on the crop and the surrounding
    # paragraphs are located. Both are null until then.
    ocr_text: str | None = None
    surrounding_text: str | None = None

    # The description a multimodal model produced from the image crop. Marked
    # nullable because it does not exist until Phase 6.7, and typed as str
    # rather than UntrustedText because it is model output, not user input —
    # the risk is hallucination rather than injection, and the distinction
    # matters for how callers decide to trust it.
    description: str | None = None

    # Chart-specific fields (FR-VIS-03). All null for non-CHART kinds.
    title: str | None = None
    chart_type: str | None = None
    x_axis_label: str | None = None
    y_axis_label: str | None = None
    units_label: str | None = None
    legend: str | None = None
    data_labels: str | None = None
    visible_trend: str | None = None

    # Diagram-specific fields (FR-VIS-04). All null for non-DIAGRAM kinds.
    # Each is a tuple of short strings — labels, named components, arrows
    # described as "A → B", visible relationships — because an ordered list
    # of items is a more useful form than a blob of prose.
    diagram_labels: tuple[str, ...] = ()
    components: tuple[str, ...] = ()
    arrows: tuple[str, ...] = ()
    visible_relationships: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_positive(self.page_number, "DocumentFigure.page_number")
        require_timezone_aware(self.created_at, "DocumentFigure.created_at")

        if self.kind not in _VISUAL_KINDS:
            raise InvariantViolationError(
                f"kind must be FIGURE, CHART or DIAGRAM — got {self.kind!r}"
            )

        if self.confidence is not None:
            require_within(self.confidence, "DocumentFigure.confidence", low=0.0, high=1.0)

    @property
    def scope(self) -> ScopeContext:
        return ScopeContext(user_id=self.user_id, knowledge_base_id=self.knowledge_base_id)

    @property
    def is_described(self) -> bool:
        """Whether Phase 6.7 has run on this figure and produced a description."""
        return self.description is not None
