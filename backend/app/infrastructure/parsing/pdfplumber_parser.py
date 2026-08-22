"""Layout-aware PDF parsing over the embedded text layer.

Reads what a PDF already knows about itself: where its characters sit, how large its
images are, how much of it was drawn as vector line work. That is enough to decide how
each page has to be read, and enough to produce elements for every page whose text layer
can be trusted. Pages it cannot read this way come back empty and are left for optical
recognition, rather than being half-read into something that looks like content.

Elements are typed by how they are set — a heading by being larger or heavier than the
body around it, a list by its markers, a caption by its label. Tables and figures are
found by looking at the page rather than at a run of text, and are recorded as regions
whose contents a later stage fills in. Ordering across columns is still to come, so
elements are ordered straight down the page for now.

pdfplumber is synchronous and CPU-bound, and the worker that calls this runs a heartbeat
on the same event loop to hold the job's lease. Parsing on that loop would stall the
heartbeat and let a lease expire while the work it covers is still running, so the whole
parse is handed to a thread.
"""

from __future__ import annotations

import asyncio
import io
import re
import uuid
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pdfplumber
import structlog

from app.domain.documents.caption_label import labels_kind, parse_caption_label
from app.domain.documents.element_classifier import ElementClassifier, ElementSignals
from app.domain.documents.entities import DocumentElement, DocumentPage, ParsedPage
from app.domain.documents.figures import DocumentFigure
from app.domain.documents.heading_stack import HeadingStack
from app.domain.documents.page_classifier import PageClassifier, PageSignals
from app.domain.documents.reading_order import LayoutBox, ReadingOrderResolver
from app.domain.documents.table_structure import TableStructure, resolve_table_structure
from app.domain.documents.tables import DocumentTable
from app.domain.enums import ElementType, PageKind, ProcessingMethod
from app.domain.errors import UploadValidationError
from app.domain.scope import ScopeContext
from app.domain.values import BoundingBox, UntrustedText

_log = structlog.get_logger(__name__)

# (x0, top, x1, bottom) in pdfplumber's downward-measured coordinates.
_Region = tuple[float, float, float, float]

# A heading text is a running header — page boilerplate rather than document structure —
# when it appears on at least this many pages AND at least this fraction of the document.
# A fraction alone misfires on tiny documents; a count alone misfires on long ones.
_RUNNING_HEADER_MIN_PAGES: int = 3
_RUNNING_HEADER_PAGE_FRACTION: float = 0.15
# Running headers appear in the top margin. Only heading drafts whose top coordinate
# (distance from the page top in pdfplumber's downward system) falls within this many
# points are candidates; structural headings in the text area are never suppressed.
_RUNNING_HEADER_TOP_PTS: float = 80.0

# Many books embed the current page number in the running header text, giving each page
# a unique string ("Overview of Azure ML | 3", "4 | Overview of Azure ML") despite an
# identical underlying title. Stripping the number before counting lets occurrences that
# differ only by page number still accumulate toward the suppression threshold.
_PAGE_NUMBER_NOISE = re.compile(r"^\d+\s*[|—–]\s*|\s*[|—–]\s*\d+$")


def _normalize_running_header(text: str) -> str:
    return _PAGE_NUMBER_NOISE.sub("", text).strip()


@dataclass(frozen=True, slots=True)
class _Draft:
    """An element found on a page, before it is given an identity and a reading order.

    Positions stay in pdfplumber's downward coordinates while ordering is decided,
    because ordering down a page is what they express directly. They are flipped to the
    upward system once, at the point the real element is built.
    """

    element_type: ElementType
    text: str
    top: float
    bottom: float
    left: float
    right: float
    font_size: float = 0.0

    # The cell grid, on table drafts only. Carried here rather than re-derived later
    # because this is the one moment the page object is open and the cells are known;
    # recovering them afterwards would mean reopening the file and detecting the same
    # region a second time, with the chance of detecting it differently.
    grid: tuple[tuple[str | None, ...], ...] | None = None

    @property
    def box(self) -> LayoutBox:
        return LayoutBox(
            left=self.left, right=self.right, top=self.top, bottom=self.bottom
        )


class PdfPlumberParser:
    """`PdfParserPort` over the embedded text layer.

    Both classifiers are injected rather than constructed here: deciding how a page must
    be read, and what a run of text is, are rules, and rules belong in the domain where
    they can be changed and tested without a PDF to hand.
    """

    def __init__(
        self,
        page_classifier: PageClassifier,
        element_classifier: ElementClassifier,
        reading_order: ReadingOrderResolver,
        *,
        paragraph_gap_multiplier: float,
        min_element_characters: int,
        min_gutter_width: float,
    ) -> None:
        self._page_classifier = page_classifier
        self._classifier = element_classifier
        self._reading_order = reading_order
        self._paragraph_gap_multiplier = paragraph_gap_multiplier
        self._min_element_characters = min_element_characters
        self._min_gutter_width = min_gutter_width

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
        # Document-level, not page-level: a section that starts near the foot of one page
        # continues onto the next, and rebuilding this per page would lose that at every
        # break — where the content has the least context of its own to fall back on.
        headings = HeadingStack()
        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                # Pre-scan for running headers before building any elements, so the
                # heading stack never enters boilerplate text and heading paths under
                # real chapter headings are clean from the start.
                running_headers = self._detect_running_headers(pdf.pages)
                parsed = [
                    self._parse_page(
                        page, number, document_id=document_id, scope=scope,
                        now=now, headings=headings,
                        running_headers=running_headers,
                    )
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
            elements=sum(len(item.elements) for item in parsed),
            tables=sum(len(item.tables) for item in parsed),
            figures=sum(len(item.figures) for item in parsed),
        )
        return parsed

    def _parse_page(
        self,
        page: Any,
        page_number: int,
        *,
        document_id: UUID,
        scope: ScopeContext,
        now: datetime,
        headings: HeadingStack,
        running_headers: frozenset[str],
    ) -> ParsedPage:
        signals = _page_signals(page)
        kind = self._page_classifier.classify(signals)

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
            return ParsedPage(page=document_page, elements=[], tables=[], figures=[])

        elements, tables, figures = self._elements_for(
            page, page_number, document_id=document_id, scope=scope,
            now=now, headings=headings, running_headers=running_headers,
        )
        return ParsedPage(page=document_page, elements=elements, tables=tables, figures=figures)

    def _detect_running_headers(self, pages: Sequence[Any]) -> frozenset[str]:
        """Normalized texts that appear in the top margin on enough pages.

        A running header — the book title or chapter name repeated at the top of every
        page — may be larger than the body (classified as HEADING) or at body size
        (classified as PARAGRAPH). Either way it corrupts retrieval: a heading-size one
        pollutes the heading stack; a paragraph-size one appears as boilerplate at the
        start of chunk text. Both are detected and both are dropped.

        Two signals together identify a running header: position (the draft's top
        coordinate falls within _RUNNING_HEADER_TOP_PTS of the page top) and frequency
        (the normalized text appears on at least _RUNNING_HEADER_MIN_PAGES pages AND on
        at least _RUNNING_HEADER_PAGE_FRACTION of the total). The returned set contains
        normalized texts; callers must normalize draft text before checking membership.
        """
        counts: Counter[str] = Counter()
        page_count = 0
        for page in pages:
            page_count += 1
            table_regions = _table_regions(page)
            body_size = _page_body_font_size(page)
            page_headings: set[str] = set()
            for draft in self._text_drafts(page, table_regions, body_size):
                if (
                    draft.element_type in (ElementType.HEADING, ElementType.PARAGRAPH)
                    and draft.top < _RUNNING_HEADER_TOP_PTS
                ):
                    normalized = _normalize_running_header(draft.text.strip())
                    if normalized:
                        page_headings.add(normalized)
            counts.update(page_headings)

        cutoff = max(
            _RUNNING_HEADER_MIN_PAGES,
            round(page_count * _RUNNING_HEADER_PAGE_FRACTION),
        )
        return frozenset(text for text, count in counts.items() if count >= cutoff)

    def _elements_for(
        self,
        page: Any,
        page_number: int,
        *,
        document_id: UUID,
        scope: ScopeContext,
        now: datetime,
        headings: HeadingStack,
        running_headers: frozenset[str],
    ) -> tuple[list[DocumentElement], list[DocumentTable], list[DocumentFigure]]:
        """Every element on the page, ordered down it, and every table and figure.

        Text runs, tables and figures are gathered separately because they are found in
        different ways, then interleaved by position. Sorting at the end rather than
        emitting each group in turn is what keeps a figure between the paragraphs it sits
        between, instead of after all of them.
        """
        page_height = float(page.height)
        body_size = _page_body_font_size(page)
        table_regions = _table_regions(page)

        drafts: list[_Draft] = []
        drafts.extend(_figure_drafts(page))
        drafts.extend(_table_drafts(page, table_regions))
        drafts.extend(self._text_drafts(page, table_regions, body_size))

        ordered = [
            drafts[index]
            for index in self._reading_order.order(
                [draft.box for draft in drafts], float(page.width)
            )
        ]

        elements: list[DocumentElement] = []
        # Kept beside the elements while both are built, because a table or figure record
        # needs the id of the element it came from, and that id does not exist until here.
        table_seeds: list[tuple[DocumentElement, _Draft]] = []
        figure_seeds: list[DocumentElement] = []

        for order, draft in enumerate(ordered):
            # Running headers are page boilerplate — drop them entirely so they neither
            # corrupt the heading stack nor appear in chunk text. Both heading-size and
            # body-size running headers are handled: position (in the top margin) and
            # normalized text membership must both hold.
            if (
                draft.element_type in (ElementType.HEADING, ElementType.PARAGRAPH)
                and draft.top < _RUNNING_HEADER_TOP_PTS
                and _normalize_running_header(draft.text.strip()) in running_headers
            ):
                continue

            element_type = draft.element_type

            # Asked once per element, in reading order, so the answer reflects the
            # section the reader would be in at that point.
            if element_type is ElementType.HEADING:
                heading_path = headings.enter(draft.text, size=draft.font_size)
            else:
                heading_path = headings.current
            element = DocumentElement(
                id=uuid.uuid4(),
                user_id=scope.user_id,
                knowledge_base_id=scope.knowledge_base_id,
                document_id=document_id,
                page_number=page_number,
                element_type=element_type,
                text=UntrustedText(draft.text),
                reading_order=order,
                processing_method=ProcessingMethod.NATIVE_TEXT,
                created_at=now,
                bounding_box=_flip(draft, page_height),
                heading_path=heading_path,
            )
            elements.append(element)
            if draft.grid is not None:
                table_seeds.append((element, draft))
            elif draft.element_type in {
                ElementType.FIGURE, ElementType.CHART, ElementType.DIAGRAM
            }:
                figure_seeds.append(element)

        tables = [
            table
            for element, draft in table_seeds
            if (
                table := _build_table(
                    element,
                    draft,
                    elements=elements,
                    scope=scope,
                    document_id=document_id,
                    now=now,
                )
            )
            is not None
        ]
        figures = [
            figure
            for element in figure_seeds
            if (
                figure := _build_figure(
                    element,
                    elements=elements,
                    scope=scope,
                    document_id=document_id,
                    now=now,
                )
            )
            is not None
        ]
        return elements, tables, figures

    def _text_drafts(
        self,
        page: Any,
        table_regions: list[_Region],
        body_size: float,
    ) -> Iterator[_Draft]:
        for block in self._blocks_by_column(page, table_regions):
            lines = [line["text"].strip() for line in block]
            text = " ".join(lines).strip()
            if len(text) < self._min_element_characters:
                continue
            element_type = self._classifier.classify(
                ElementSignals(
                    text=text,
                    font_size=_block_font_size(block),
                    page_body_font_size=body_size,
                    is_bold=_block_is_bold(block),
                    line_count=len(block),
                )
            )
            # Prose wraps mid-sentence, so its lines rejoin with a space. A list does
            # not wrap — each line is a separate item — and joining those with a space
            # runs them together into one sentence that was never written.
            if element_type is ElementType.LIST:
                text = "\n".join(lines).strip()
            yield _Draft(
                element_type=element_type,
                text=text,
                top=min(float(line["top"]) for line in block),
                bottom=max(float(line["bottom"]) for line in block),
                left=min(float(line["x0"]) for line in block),
                right=max(float(line["x1"]) for line in block),
                font_size=_block_font_size(block),
            )

    def _blocks_by_column(
        self, page: Any, table_regions: list[_Region]
    ) -> Iterator[list[dict[str, Any]]]:
        """Paragraph blocks, grouped within each column rather than across the page.

        Columns have to be found before lines are grouped, not after. Two columns put
        their lines at the same heights, so grouping by vertical spacing alone weaves
        them together into paragraphs that read straight across the gutter — text that
        is wrong in a way no later reordering can undo, because the lines have already
        been joined into a single string.
        """
        lines = [
            line
            for line in _text_lines(page, self._min_gutter_width)
            # Text inside a table is reported as ordinary lines as well. Left in, it
            # would appear twice — once flattened into a paragraph and once inside
            # the table element — and the flattened copy is the one that would mix
            # rows together and lose which column a number came from.
            if not _falls_inside(line, table_regions)
        ]
        if not lines:
            return

        gutters = self._reading_order.find_gutters([_line_box(line) for line in lines])
        if not gutters:
            yield from self._paragraph_blocks(lines)
            return

        by_column: dict[int, list[dict[str, Any]]] = {}
        for line in lines:
            column = self._reading_order.column_of(_line_box(line), gutters)
            by_column.setdefault(column, []).append(line)

        for column in sorted(by_column):
            yield from self._paragraph_blocks(by_column[column])

    def _paragraph_blocks(
        self, lines: list[dict[str, Any]]
    ) -> Iterator[list[dict[str, Any]]]:
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
        ordered = sorted(lines, key=lambda line: (line["top"], line["x0"]))
        block: list[dict[str, Any]] = []
        for line in ordered:
            if block and self._starts_new_block(block[-1], line):
                yield block
                block = []
            block.append(line)
        if block:
            yield block

    def _starts_new_block(
        self, previous: dict[str, Any], line: dict[str, Any]
    ) -> bool:
        """Whether this line begins a new paragraph rather than continuing one.

        Two things end a paragraph. A wide enough vertical gap is the obvious one. A
        change of type size is the other, and it matters just as much: a chapter title
        immediately above a section title sits at ordinary leading, and without this
        the two would be joined into one element carrying both their names.
        """
        previous_height = _line_height(previous)
        height = _line_height(line)
        reference = max(min(previous_height, height), 1.0)
        gap = float(line["top"]) - float(previous["bottom"])
        if gap > reference * self._paragraph_gap_multiplier:
            return True
        return abs(previous_height - height) > max(previous_height, height) * 0.15


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


def _line_box(line: dict[str, Any]) -> LayoutBox:
    return LayoutBox(
        left=float(line["x0"]),
        right=float(line["x1"]),
        top=float(line["top"]),
        bottom=float(line["bottom"]),
    )


def _line_height(line: dict[str, Any]) -> float:
    return float(line["bottom"]) - float(line["top"])


# ---------------------------------------------------------------------------
# Tables and figures — found by looking at the page rather than at a run of text
# ---------------------------------------------------------------------------


# How far from a table's edge a caption may sit and still belong to it, as a multiple of
# the caption's own height. Captions are set close to what they describe; a limit stated
# in the caption's own terms travels between page sizes better than one in points.
_CAPTION_REACH = 3.0


def _caption_for(
    element: DocumentElement,
    elements: Sequence[DocumentElement],
    *,
    kind: ElementType,
) -> UntrustedText | None:
    """The nearest caption that names a specific kind of object, above or below.

    Both directions are searched because the convention is not settled — most style
    guides put a table's caption above it and a figure's below, but plenty of textbooks
    do the opposite, and a caption on the wrong side is still that object's caption.
    Nearest wins, so a page with a caption on each side attaches the closer one.

    The `kind` filter stops a figure's caption being claimed by a table sitting next to
    it — a caption that says "Figure 3.2" cannot describe a table, and accepting it
    would give the table a description of something else entirely.
    """
    if element.bounding_box is None:
        return None

    best: tuple[float, DocumentElement] | None = None

    for candidate in elements:
        if candidate.element_type is not ElementType.CAPTION:
            continue
        if candidate.bounding_box is None:
            continue
        if not labels_kind(candidate.text.value, kind):
            continue

        height = candidate.bounding_box.y1 - candidate.bounding_box.y0
        # Gap between the two boxes: positive when the caption sits clear of the element,
        # zero when they touch or overlap.
        gap = max(
            element.bounding_box.y0 - candidate.bounding_box.y1,
            candidate.bounding_box.y0 - element.bounding_box.y1,
            0.0,
        )
        if gap > height * _CAPTION_REACH:
            continue
        if best is None or gap < best[0]:
            best = (gap, candidate)

    return best[1].text if best else None


def _build_table(
    element: DocumentElement,
    draft: _Draft,
    *,
    elements: Sequence[DocumentElement],
    scope: ScopeContext,
    document_id: UUID,
    now: datetime,
) -> DocumentTable | None:
    """Read one detected region into a table record, or nothing if it holds no text.

    A region whose cells are all blank is a detection error rather than an empty table,
    so it produces no record. The element stays either way — it still marks a place on
    the page — but nothing claims to have read a table there.
    """
    if draft.grid is None or element.bounding_box is None:
        return None

    structure = resolve_table_structure(draft.grid)
    if structure is None:
        return None

    caption = _caption_for(element, elements, kind=ElementType.TABLE)
    label = parse_caption_label(caption.value) if caption is not None else None

    return DocumentTable(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        document_id=document_id,
        source_element_id=element.id,
        page_number=element.page_number,
        headers=structure.headers,
        rows=structure.rows,
        units=structure.units,
        caption=caption,
        number=label.number if label is not None else None,
        bounding_box=element.bounding_box,
        created_at=now,
        # A grid that arrived ragged, or whose columns had to be named by position, was
        # read less certainly than one that did neither. Stated as a score rather than a
        # flag so a reader downstream can weigh it alongside everything else.
        confidence=_table_confidence(structure),
    )


def _build_figure(
    element: DocumentElement,
    *,
    elements: Sequence[DocumentElement],
    scope: ScopeContext,
    document_id: UUID,
    now: datetime,
) -> DocumentFigure | None:
    """Build a figure record for a detected visual element.

    Returns None for an element with no bounding box — without one there is
    no region on the page to cite or highlight.

    pdfplumber detects images as FIGURE elements. Charts and diagrams cannot be
    distinguished from figures at detection time, so every visual starts as a
    FIGURE record and will be reclassified in Phase 6.7 after image analysis.
    """
    if element.bounding_box is None:
        return None

    caption = _caption_for(element, elements, kind=ElementType.FIGURE)
    label = parse_caption_label(caption.value) if caption is not None else None

    return DocumentFigure(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        document_id=document_id,
        source_element_id=element.id,
        page_number=element.page_number,
        kind=element.element_type,
        bounding_box=element.bounding_box,
        created_at=now,
        caption=caption,
        number=label.number if label is not None else None,
    )


def _table_confidence(structure: TableStructure) -> float:
    """How well the grid read, as a score between zero and one.

    Deliberately coarse. There is no calibration behind these numbers yet — they encode
    an ordering, that a clean read beats a ragged one and that both beat a table whose
    columns nobody named, and that ordering is what a caller needs before any of it has
    been measured against real documents.
    """
    score = 1.0
    if structure.was_ragged:
        score -= 0.3
    if structure.header_assumed:
        score -= 0.2
    return max(score, 0.0)


def _table_regions(page: Any) -> list[_Region]:
    try:
        return [tuple(float(value) for value in table.bbox) for table in page.find_tables()]  # type: ignore[misc]
    except Exception:
        # Table detection is heuristic and its failure is not a reason to lose the page.
        # Without regions the text inside a table is read as prose, which is the
        # behaviour of the step before this one rather than a new kind of wrong.
        return []


def _table_drafts(page: Any, regions: list[_Region]) -> Iterator[_Draft]:
    """One element per detected table, carrying both a joined reading and the raw grid.

    The joined text is what puts the table into reading order among the paragraphs, and
    is what a search over element text will match. The grid alongside it is what lets the
    same region become a table record with named columns — a question about a particular
    column cannot be answered from the joined form, because which value sat under which
    heading is exactly what joining discards.
    """
    for region, table in zip(regions, page.find_tables(), strict=False):
        rows = table.extract()
        text = "\n".join(
            " | ".join(cell.strip() for cell in row if cell) for row in rows if any(row)
        ).strip()
        x0, top, x1, bottom = region
        yield _Draft(
            element_type=ElementType.TABLE,
            text=text,
            top=top,
            bottom=bottom,
            left=x0,
            right=x1,
            grid=tuple(tuple(row) for row in rows),
        )


def _figure_drafts(page: Any) -> Iterator[_Draft]:
    """One element per embedded image, carrying its position and no text.

    A figure has nothing to say until something looks at it. Recording it empty is what
    lets a later stage find it — the alternative, inventing a description now, would put
    text into the document that the document does not contain.
    """
    for image in page.images:
        yield _Draft(
            element_type=ElementType.FIGURE,
            text="",
            top=float(image["top"]),
            bottom=float(image["bottom"]),
            left=float(image["x0"]),
            right=float(image["x1"]),
        )


def _falls_inside(line: dict[str, Any], regions: list[_Region]) -> bool:
    """Whether a line's centre sits within any region.

    The centre rather than the whole box, so a line that grazes a table's border by a
    fraction of a point is still judged by where it actually is.
    """
    mid_x = (float(line["x0"]) + float(line["x1"])) / 2
    mid_y = (float(line["top"]) + float(line["bottom"])) / 2
    return any(
        x0 <= mid_x <= x1 and top <= mid_y <= bottom for x0, top, x1, bottom in regions
    )


# ---------------------------------------------------------------------------
# Type signals
# ---------------------------------------------------------------------------


def _page_body_font_size(page: Any) -> float:
    """The page's dominant type size — what every element on it is judged against.

    The median across characters rather than the mean, so a page with one very large
    title is still measured by its body text. Falls back to a nominal size on a page with
    no characters, where nothing will be classified anyway.
    """
    sizes = sorted(float(char["size"]) for char in page.chars if char.get("size"))
    if not sizes:
        return 10.0
    return sizes[len(sizes) // 2]


def _text_lines(page: Any, min_gutter_width: float) -> list[dict[str, Any]]:
    """Words assembled into lines, ending a line at any gap wide enough to be a gutter.

    On a single-column page no gap is ever that wide, so every row becomes one line and
    the result matches what a line-based extractor would have produced. On a multi-column
    page the same rule separates the columns, which is the case that cannot be repaired
    afterwards.
    """
    words = page.extract_words(extra_attrs=["size", "fontname"])
    if not words:
        return []

    lines: list[dict[str, Any]] = []
    for row in _rows(words):
        segment: list[dict[str, Any]] = []
        for word in sorted(row, key=lambda w: float(w["x0"])):
            if segment and float(word["x0"]) - float(segment[-1]["x1"]) >= min_gutter_width:
                lines.append(_line_from(segment))
                segment = []
            segment.append(word)
        if segment:
            lines.append(_line_from(segment))
    return lines


def _rows(words: Sequence[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    """Words gathered into visual rows by vertical position.

    Two words belong to the same row when their vertical extents overlap for most of
    their height, which tolerates the small baseline differences that ordinary typesetting
    produces without merging genuinely separate lines.
    """
    row: list[dict[str, Any]] = []
    for word in sorted(words, key=lambda w: (float(w["top"]), float(w["x0"]))):
        if row:
            reference = row[0]
            height = max(float(reference["bottom"]) - float(reference["top"]), 1.0)
            if abs(float(word["top"]) - float(reference["top"])) > height * 0.5:
                yield row
                row = []
        row.append(word)
    if row:
        yield row


def _line_from(words: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "text": " ".join(str(word["text"]) for word in words),
        "x0": min(float(word["x0"]) for word in words),
        "x1": max(float(word["x1"]) for word in words),
        "top": min(float(word["top"]) for word in words),
        "bottom": max(float(word["bottom"]) for word in words),
        "words": list(words),
    }


def _block_font_size(block: Sequence[dict[str, Any]]) -> float:
    sizes = sorted(
        float(word["size"])
        for line in block
        for word in line.get("words", ())
        if word.get("size")
    )
    if not sizes:
        return 10.0
    return sizes[len(sizes) // 2]


def _block_is_bold(block: Sequence[dict[str, Any]]) -> bool:
    """Whether most of the block is set in a bold face.

    Most rather than any, because a single emphasised word inside a sentence does not
    make the sentence a heading.
    """
    fonts = [
        str(word.get("fontname", ""))
        for line in block
        for word in line.get("words", ())
    ]
    if not fonts:
        return False
    bold = sum("bold" in font.lower() or "black" in font.lower() for font in fonts)
    return bold * 2 > len(fonts)


def _flip(draft: _Draft, page_height: float) -> BoundingBox | None:
    """A draft's position as a bounding box, measured upward from the bottom.

    Returns None for a degenerate region rather than a zero-area box, which the value
    object refuses and which would in any case describe nothing.
    """
    y0 = page_height - draft.bottom
    y1 = page_height - draft.top
    if draft.right <= draft.left or y1 <= y0:
        return None
    return BoundingBox(x0=draft.left, y0=y0, x1=draft.right, y1=y1)
