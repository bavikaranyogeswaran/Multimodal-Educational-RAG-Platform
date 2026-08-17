"""Layout-aware PDF parsing over the embedded text layer.

Reads what a PDF already knows about itself: where its characters sit, how large its
images are, how much of it was drawn as vector line work. That is enough to decide how
each page has to be read, and enough to produce elements for every page whose text layer
can be trusted. Pages it cannot read this way come back empty and are left for optical
recognition, rather than being half-read into something that looks like content.

Elements are emitted as paragraphs here and nothing finer. Distinguishing a heading from
a paragraph, and ordering elements across columns, both need judgements this step does
not make yet; emitting everything as a paragraph is the honest placeholder, because it
claims only what has actually been established.

pdfplumber is synchronous and CPU-bound, and the worker that calls this runs a heartbeat
on the same event loop to hold the job's lease. Parsing on that loop would stall the
heartbeat and let a lease expire while the work it covers is still running, so the whole
parse is handed to a thread.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pdfplumber
import structlog

from app.domain.documents.entities import DocumentElement, DocumentPage
from app.domain.documents.page_classifier import PageClassifier, PageSignals
from app.domain.enums import ElementType, PageKind, ProcessingMethod
from app.domain.errors import UploadValidationError
from app.domain.scope import ScopeContext
from app.domain.values import BoundingBox, UntrustedText

_log = structlog.get_logger(__name__)

ParsedPage = tuple[DocumentPage, Sequence[DocumentElement]]


class PdfPlumberParser:
    """`PdfParserPort` over the embedded text layer.

    The classifier is injected rather than constructed here: deciding how a page must be
    read is a rule, and rules belong in the domain where they can be changed without a
    PDF to hand.
    """

    def __init__(
        self,
        classifier: PageClassifier,
        *,
        paragraph_gap_multiplier: float,
        min_element_characters: int,
    ) -> None:
        self._classifier = classifier
        self._paragraph_gap_multiplier = paragraph_gap_multiplier
        self._min_element_characters = min_element_characters

    async def parse(
        self,
        data: bytes,
        *,
        document_id: UUID,
        scope: ScopeContext,
    ) -> Sequence[ParsedPage]:
        return await asyncio.to_thread(self._parse_blocking, data, document_id, scope)

    # -----------------------------------------------------------------------
    # Everything below runs on a worker thread
    # -----------------------------------------------------------------------

    def _parse_blocking(
        self,
        data: bytes,
        document_id: UUID,
        scope: ScopeContext,
    ) -> list[ParsedPage]:
        now = datetime.now(UTC)
        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                parsed = [
                    self._parse_page(page, number, document_id, scope, now)
                    for number, page in enumerate(pdf.pages, start=1)
                ]
        except Exception as exc:
            # Deliberately broad: pdfplumber surfaces malformed structure, unsupported
            # encryption and truncated files as several unrelated exception types from
            # its own dependencies, and the caller's response to all of them is the
            # same. Half a document is worse than none, so nothing partial is returned.
            raise UploadValidationError(f"could not read PDF: {exc}") from exc

        # Checked after the parse rather than inside it: a structurally valid file
        # holding no pages is a different failure from one that could not be read, and
        # keeping them apart means the broad handler above is not also the place where
        # this decision is made.
        if not parsed:
            raise UploadValidationError("PDF contains no pages")

        _log.info(
            "pdf_parsed",
            document_id=str(document_id),
            pages=len(parsed),
            elements=sum(len(elements) for _, elements in parsed),
        )
        return parsed

    def _parse_page(
        self,
        page: Any,
        page_number: int,
        document_id: UUID,
        scope: ScopeContext,
        now: datetime,
    ) -> ParsedPage:
        signals = _page_signals(page)
        kind = self._classifier.classify(signals)

        document_page = DocumentPage(
            id=uuid.uuid4(),
            user_id=scope.user_id,
            knowledge_base_id=scope.knowledge_base_id,
            document_id=document_id,
            page_number=page_number,
            kind=kind,
            width=float(page.width),
            height=float(page.height),
            rotation=_normalised_rotation(page),
        )

        # The port's contract: pages needing recognition come back without elements, so
        # a caller cannot mistake a partial read for a complete one.
        if kind in {PageKind.SCANNED, PageKind.COMPLEX}:
            return document_page, []

        elements = list(self._elements_for(page, page_number, document_id, scope, now))
        return document_page, elements

    def _elements_for(
        self,
        page: Any,
        page_number: int,
        document_id: UUID,
        scope: ScopeContext,
        now: datetime,
    ) -> Iterator[DocumentElement]:
        page_height = float(page.height)
        reading_order = 0
        for block in self._paragraph_blocks(page):
            text = " ".join(line["text"].strip() for line in block).strip()
            if len(text) < self._min_element_characters:
                continue
            yield DocumentElement(
                id=uuid.uuid4(),
                user_id=scope.user_id,
                knowledge_base_id=scope.knowledge_base_id,
                document_id=document_id,
                page_number=page_number,
                element_type=ElementType.PARAGRAPH,
                text=UntrustedText(text),
                reading_order=reading_order,
                processing_method=ProcessingMethod.NATIVE_TEXT,
                created_at=now,
                bounding_box=_block_bounds(block, page_height),
            )
            reading_order += 1

    def _paragraph_blocks(self, page: Any) -> Iterator[list[dict[str, Any]]]:
        """Group text lines into paragraphs on vertical spacing.

        Lines arrive top to bottom. A gap larger than a line height by more than the
        configured multiple starts a new paragraph; anything closer is ordinary leading
        within one. Judging the gap relative to the lines rather than in absolute points
        is what lets one threshold serve both body text and headings.

        The gap is measured against the *smaller* of the two lines it separates. Where
        both are the same size that makes no difference, and where they are not, the
        smaller one is the right reference: the space under a heading is modest next to
        the heading and generous next to the body text below it, and it is a paragraph
        break either way. Taking the larger would swallow every heading into the
        paragraph that follows it.
        """
        lines = sorted(page.extract_text_lines(), key=lambda line: (line["top"], line["x0"]))
        block: list[dict[str, Any]] = []
        for line in lines:
            if block:
                previous = block[-1]
                reference = max(min(_line_height(previous), _line_height(line)), 1.0)
                gap = float(line["top"]) - float(previous["bottom"])
                if gap > reference * self._paragraph_gap_multiplier:
                    yield block
                    block = []
            block.append(line)
        if block:
            yield block


# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------


def _page_signals(page: Any) -> PageSignals:
    page_area = float(page.width) * float(page.height)
    if page_area <= 0:
        # A page with no extent cannot be measured against, and every ratio would be a
        # division by zero. Treated as empty so it classifies rather than raising.
        return PageSignals.blank()

    return PageSignals(
        native_character_count=len(page.chars),
        text_area_ratio=_covered_ratio(page.extract_text_lines(), page_area),
        image_area_ratio=_covered_ratio(page.images, page_area),
        vector_drawing_count=len(page.lines) + len(page.curves) + len(page.rects),
    )


def _covered_ratio(regions: Sequence[dict[str, Any]], page_area: float) -> float:
    """Share of the page covered by these regions, capped at the whole page.

    Areas are summed rather than unioned. Overlap therefore counts twice, which is why
    the result is capped — the measurement is meant to separate a page of text from a
    page of picture, and a true union costs more than that distinction is worth.
    """
    total = 0.0
    for region in regions:
        width = float(region["x1"]) - float(region["x0"])
        height = abs(float(region["bottom"]) - float(region["top"]))
        if width > 0 and height > 0:
            total += width * height
    return min(total / page_area, 1.0)


def _normalised_rotation(page: Any) -> int:
    """Rotation as one of the four quarter turns a page entity accepts.

    PDFs in the wild carry negative rotations and multiples beyond a full turn, and
    anything that is not a quarter turn is discarded rather than rounded — guessing
    which way a page nearly faces would put a wrong number where a known one belongs.
    """
    raw = getattr(page, "rotation", 0) or 0
    try:
        normalised = int(raw) % 360
    except (TypeError, ValueError):
        return 0
    return normalised if normalised in {0, 90, 180, 270} else 0


def _line_height(line: dict[str, Any]) -> float:
    return float(line["bottom"]) - float(line["top"])


def _block_bounds(block: Sequence[dict[str, Any]], page_height: float) -> BoundingBox | None:
    """One box around every line in the paragraph, in bottom-left origin coordinates.

    The two coordinate systems have to be reconciled here. pdfplumber measures `top` and
    `bottom` downwards from the top of the page; `BoundingBox` measures upwards from the
    bottom, which is what a PDF viewer and a citation highlight both expect. Subtracting
    from the page height flips the axis, and it also swaps which value is which — the
    line's `top`, being the smaller number in a downward system, becomes the larger `y1`
    in an upward one.

    Returns None when the lines carry no usable extent: a zero-area box fails the value
    object's invariant, and no box is a truthful answer where a degenerate one is not.
    """
    x0 = min(float(line["x0"]) for line in block)
    x1 = max(float(line["x1"]) for line in block)
    y0 = page_height - max(float(line["bottom"]) for line in block)
    y1 = page_height - min(float(line["top"]) for line in block)
    if x1 <= x0 or y1 <= y0:
        return None
    return BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
