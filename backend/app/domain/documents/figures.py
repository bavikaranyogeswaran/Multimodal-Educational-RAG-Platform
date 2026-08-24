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

    # R2 storage key for the cropped image. Set during ingestion; null on records
    # from documents processed before step 6.5, or when the page failed to render.
    crop_key: str | None = None

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


def to_embedding_text(figure: DocumentFigure) -> str:
    """The figure as prose a question can match against.

    A figure region carries no text of its own — what a reader would call its content
    lives in the caption the document gave it and in what a model saw when it looked at
    the image. Gathered here into one passage so the figure is retrievable as itself,
    rather than being reachable only through whatever paragraph happens to sit beside it.

    Ordered by how a person would describe the figure aloud: what it is called, what it
    shows, what is written on it, then the structure a chart or a diagram adds. Anything
    absent is skipped rather than rendered as an empty heading, so a figure the vision
    model never reached still returns its caption instead of a page of blank labels.
    """
    lines: list[str] = []

    label = _label(figure)
    if label:
        lines.append(label)
    if figure.title:
        lines.append(figure.title)
    if figure.description:
        lines.append(figure.description)
    if figure.ocr_text:
        lines.append(figure.ocr_text)

    lines.extend(_chart_lines(figure))
    lines.extend(_diagram_lines(figure))

    # The caption alone is worth retrieving. A student asking about a figure should find
    # where it sits even when nothing could be read out of the image itself.
    return "\n".join(line.strip() for line in lines if line.strip()).strip()


def _caption_text(figure: DocumentFigure) -> str:
    return figure.caption.value.strip() if figure.caption is not None else ""


def _label(figure: DocumentFigure) -> str:
    """What the figure is called, without saying its number twice.

    A caption is usually read off the page complete with its own label, so "Figure 1" and
    a caption of "Figure 1. Azure ML Studio" would otherwise render as "1 Figure 1. Azure
    ML Studio". The number is prepended only when the caption does not already carry it.
    """
    caption = _caption_text(figure)
    number = (figure.number or "").strip()
    if not number:
        return caption
    if not caption:
        return number
    return caption if number.lower() in caption.lower() else f"{number} {caption}"


def _chart_lines(figure: DocumentFigure) -> list[str]:
    """What a chart adds: its axes, its units, and the shape the model read off it."""
    lines: list[str] = []
    if figure.chart_type:
        lines.append(f"{figure.chart_type} chart.")

    axes = [
        f"{name} {value}"
        for name, value in (
            ("x axis", figure.x_axis_label),
            ("y axis", figure.y_axis_label),
            ("units", figure.units_label),
        )
        if value
    ]
    if axes:
        lines.append(", ".join(axes) + ".")

    for value in (figure.legend, figure.data_labels, figure.visible_trend):
        if value:
            lines.append(value)
    return lines


def _diagram_lines(figure: DocumentFigure) -> list[str]:
    """What a diagram adds: the parts it names and the connections drawn between them."""
    lines: list[str] = []
    for label, items in (
        ("", figure.diagram_labels),
        ("Components", figure.components),
        ("Connections", figure.arrows),
        ("Relationships", figure.visible_relationships),
    ):
        if not items:
            continue
        joined = ", ".join(item.strip() for item in items if item.strip())
        if joined:
            lines.append(f"{label}: {joined}." if label else joined)
    return lines
