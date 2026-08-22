"""Uploaded documents and what parsing extracts from them.

Three entities in a containment chain: a document has pages, and a page has elements. The
document owns the lifecycle; the pages and elements are what the ingestion pipeline
produces as it advances that lifecycle.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from uuid import UUID

from app.domain.documents.figures import DocumentFigure
from app.domain.documents.tables import DocumentTable
from app.domain.enums import DocumentStatus, ElementType, PageKind, ProcessingMethod
from app.domain.errors import IllegalTransitionError, InvariantViolationError
from app.domain.invariants import (
    require_non_blank,
    require_non_negative,
    require_ordered,
    require_positive,
    require_timezone_aware,
    require_within,
)
from app.domain.scope import ScopeContext
from app.domain.values import BoundingBox, HeadingPath, UntrustedText


@dataclass(frozen=True, slots=True)
class Document:
    """An uploaded PDF or image and its position in the ingestion lifecycle.

    Status is a state machine rather than a free string. The transitions it permits are
    the ones that make sense; the ones it refuses are the ones that would leave the
    system describing itself incorrectly — a completed document claiming to be pending, or
    a document under deletion becoming searchable again.
    """

    id: UUID
    user_id: UUID
    knowledge_base_id: UUID
    filename: str
    content_type: str
    byte_size: int
    storage_key: str
    created_at: datetime
    updated_at: datetime

    status: DocumentStatus = DocumentStatus.PENDING
    title: str | None = None
    page_count: int | None = None
    checksum: str | None = None
    language: str = "en"
    failure_reason: str | None = None
    processed_at: datetime | None = None

    def __post_init__(self) -> None:
        require_non_blank(self.filename, "Document.filename")
        require_non_blank(self.content_type, "Document.content_type")
        require_non_blank(self.storage_key, "Document.storage_key")
        require_positive(self.byte_size, "Document.byte_size")
        require_timezone_aware(self.created_at, "Document.created_at")
        require_timezone_aware(self.updated_at, "Document.updated_at")
        require_ordered(
            self.created_at,
            self.updated_at,
            earlier_field="created_at",
            later_field="updated_at",
        )

        if self.page_count is not None:
            require_positive(self.page_count, "Document.page_count")
        if self.processed_at is not None:
            require_timezone_aware(self.processed_at, "Document.processed_at")

        # A failure with no stated reason is one nobody can act on, and the student is
        # told only that something went wrong.
        if self.status is DocumentStatus.FAILED and not self.failure_reason:
            raise InvariantViolationError("a failed Document must carry a failure_reason")
        if self.status is not DocumentStatus.FAILED and self.failure_reason:
            raise InvariantViolationError(
                f"failure_reason is set but status is {self.status}; clear it on recovery"
            )
        # Completion means the pipeline ran to the end, which is not describable without
        # knowing how many pages it covered.
        if self.status is DocumentStatus.COMPLETED and self.page_count is None:
            raise InvariantViolationError("a completed Document must know its page_count")

    @property
    def scope(self) -> ScopeContext:
        return ScopeContext(user_id=self.user_id, knowledge_base_id=self.knowledge_base_id)

    @property
    def is_retrievable(self) -> bool:
        """Content is searchable only once ingestion has finished successfully."""
        return self.status.is_retrievable

    def _transition(self, target: DocumentStatus) -> None:
        if not self.status.can_transition_to(target):
            raise IllegalTransitionError("Document", self.status, target)

    def mark_processing(self, *, now: datetime) -> Document:
        """Begin, or begin again — reprocessing an indexed document lands here too."""
        self._transition(DocumentStatus.PROCESSING)
        return replace(
            self,
            status=DocumentStatus.PROCESSING,
            failure_reason=None,
            updated_at=now,
        )

    def mark_completed(self, *, page_count: int, now: datetime) -> Document:
        self._transition(DocumentStatus.COMPLETED)
        require_positive(page_count, "page_count")
        return replace(
            self,
            status=DocumentStatus.COMPLETED,
            page_count=page_count,
            failure_reason=None,
            processed_at=now,
            updated_at=now,
        )

    def mark_failed(self, reason: str, *, now: datetime) -> Document:
        self._transition(DocumentStatus.FAILED)
        require_non_blank(reason, "failure reason")
        return replace(
            self,
            status=DocumentStatus.FAILED,
            failure_reason=reason.strip(),
            updated_at=now,
        )

    def requeue(self, *, now: datetime) -> Document:
        """Return a failed document to the queue for another attempt."""
        self._transition(DocumentStatus.PENDING)
        return replace(
            self,
            status=DocumentStatus.PENDING,
            failure_reason=None,
            updated_at=now,
        )

    def mark_deleting(self, *, now: datetime) -> Document:
        """Block retrieval immediately, before anything has actually been removed.

        This is the point at which the document stops being searchable. The deletion job
        that follows removes files and rows, but the window between the two must not be
        one where deleted content can still be cited.
        """
        self._transition(DocumentStatus.DELETING)
        return replace(self, status=DocumentStatus.DELETING, updated_at=now)


@dataclass(frozen=True, slots=True)
class DocumentPage:
    """One page, and how it was decided the page should be read.

    The classification is recorded rather than recomputed, so a document can be
    reprocessed without re-deciding, and so an unexpectedly high proportion of pages
    needing the heavy fallback is visible as data rather than inferred from timings.
    """

    id: UUID
    user_id: UUID
    knowledge_base_id: UUID
    document_id: UUID
    page_number: int
    kind: PageKind
    width: float
    height: float

    rotation: int = 0
    ocr_confidence: float | None = None
    processed_at: datetime | None = None

    def __post_init__(self) -> None:
        require_positive(self.page_number, "DocumentPage.page_number")
        require_positive(self.width, "DocumentPage.width")
        require_positive(self.height, "DocumentPage.height")

        if self.rotation not in {0, 90, 180, 270}:
            raise InvariantViolationError(
                f"DocumentPage.rotation must be 0, 90, 180 or 270, got {self.rotation}"
            )
        if self.ocr_confidence is not None:
            require_within(self.ocr_confidence, "DocumentPage.ocr_confidence", low=0.0, high=1.0)
        if self.processed_at is not None:
            require_timezone_aware(self.processed_at, "DocumentPage.processed_at")

    @property
    def scope(self) -> ScopeContext:
        return ScopeContext(user_id=self.user_id, knowledge_base_id=self.knowledge_base_id)

    @property
    def needs_ocr(self) -> bool:
        return self.kind in {PageKind.SCANNED, PageKind.MIXED, PageKind.COMPLEX}

    @property
    def is_landscape(self) -> bool:
        return self.width > self.height


@dataclass(frozen=True, slots=True)
class DocumentElement:
    """One structural element on a page, with its position and provenance.

    Elements are what layout-aware parsing produces instead of flattened text, which is
    what keeps table rows out of paragraphs and captions attached to their figures.

    The text is `UntrustedText`: it came out of a file a student uploaded, and anything
    written in that file is evidence to be read rather than instruction to be followed.
    """

    id: UUID
    user_id: UUID
    knowledge_base_id: UUID
    document_id: UUID
    page_number: int
    element_type: ElementType
    text: UntrustedText
    reading_order: int
    processing_method: ProcessingMethod
    created_at: datetime

    bounding_box: BoundingBox | None = None
    heading_path: HeadingPath = field(default_factory=HeadingPath.root)
    confidence: float | None = None

    def __post_init__(self) -> None:
        require_positive(self.page_number, "DocumentElement.page_number")
        require_non_negative(self.reading_order, "DocumentElement.reading_order")
        require_timezone_aware(self.created_at, "DocumentElement.created_at")

        if self.confidence is not None:
            require_within(self.confidence, "DocumentElement.confidence", low=0.0, high=1.0)

        # Anything read by OCR was read from a rendered region, so its location on the
        # page is known. An element without one cannot be cited or highlighted, and a
        # citation that cannot be opened is not much of a citation.
        if self.processing_method in {ProcessingMethod.OCR, ProcessingMethod.OCR_VL}:
            if self.bounding_box is None:
                raise InvariantViolationError(
                    f"an element produced by {self.processing_method} must carry a bounding_box"
                )
            if self.confidence is None:
                raise InvariantViolationError(
                    f"an element produced by {self.processing_method} must carry a confidence"
                )

    @property
    def scope(self) -> ScopeContext:
        return ScopeContext(user_id=self.user_id, knowledge_base_id=self.knowledge_base_id)

    @property
    def is_visual(self) -> bool:
        """Whether this element is something a student can select and ask about."""
        return self.element_type in {
            ElementType.FIGURE,
            ElementType.CHART,
            ElementType.DIAGRAM,
            ElementType.TABLE,
        }

    @property
    def is_low_confidence(self) -> bool:
        """Below this, extraction is doubtful enough to be worth showing the student.

        Only meaningful where a confidence exists; text read from a PDF's own text layer
        was not guessed at.
        """
        return self.confidence is not None and self.confidence < 0.6

    def with_heading_path(self, heading_path: HeadingPath) -> DocumentElement:
        """Attach section context, assigned once the page's heading structure is known."""
        return replace(self, heading_path=heading_path)


@dataclass(frozen=True, slots=True)
class ParsedPage:
    """What reading one page produced: the page itself, its elements, and its tables.

    Tables travel alongside the elements rather than inside them because they are a
    different kind of thing. An element is a run of the page in reading order, and a
    table is one — it has a position among the paragraphs and is ordered with them. But
    a table also has a grid, and a grid does not fit in a field called `text`. The two
    records describe the same region for different purposes, and each names the other.

    Replaced a bare tuple, which had been declared separately in the parser and in the
    ingestion command. Two definitions of the same shape drift, and a third field would
    have had to be added to both.
    """

    page: DocumentPage
    elements: Sequence[DocumentElement]
    tables: Sequence[DocumentTable] = ()
    figures: Sequence[DocumentFigure] = ()
