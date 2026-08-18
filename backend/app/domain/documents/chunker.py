"""Split a parsed document into the passages retrieval will search.

Chunking decides what a search can return, and it does so before any search exists. A
boundary in the wrong place removes an answer from the index permanently: the sentence
that resolves a question sits half in one chunk and half in the next, and neither half
says enough to be retrieved. No amount of reranking recovers it, because there is nothing
left to rank.

So boundaries are placed where the document already has them. A section ends, a paragraph
ends, and — only where a single paragraph is too long to stand alone — a sentence ends.
Falling to a lower level only when the level above cannot serve is what keeps chunks
whole: most of them are simply the paragraphs somebody wrote.

Chunks come in two tiers, because searching and reading want opposite sizes. What a query
is matched against is the child: small, so a hit is not diluted by paragraphs that had
nothing to do with the question. What the model is then given is the parent: the
surrounding stretch of the section, which is where the sentence before the answer lives.
Matching against a passage that large would blur the match; answering from one that small
would strand the answer without its context. Both are produced here, and every child names
the parent it was cut from.

Three rules shape the rest.

A chunk never spans two sections. Retrieval presents a fragment with the heading path it
came from, and a chunk straddling a boundary belongs to two of them and can be honestly
labelled with neither.

Tables and figures are never merged into prose. A table is retrievable as a table, its
rows kept together, because rows scattered through sentences lose which column a number
came from — and that is exactly the sort of question a student asks of a table.

Consecutive chunks overlap. A sentence at a boundary is otherwise reachable from neither
side, and the overlap is real trailing text from the previous chunk rather than a
restatement, so a match on it points somewhere the passage actually exists.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from app.domain.documents.entities import DocumentElement
from app.domain.enums import ChunkType, ElementType
from app.domain.errors import InvariantViolationError
from app.domain.invariants import require_positive
from app.domain.sentences import split_sentences
from app.domain.values import BoundingBox, HeadingPath

#: Element types that become chunks of their own rather than joining the prose around
#: them. Their content is structured, and flattening it into sentences destroys the
#: structure that makes it answerable.
_STANDALONE: dict[ElementType, ChunkType] = {
    ElementType.TABLE: ChunkType.TABLE,
    ElementType.FIGURE: ChunkType.FIGURE,
    ElementType.CHART: ChunkType.CHART,
    ElementType.DIAGRAM: ChunkType.DIAGRAM,
    ElementType.FORMULA: ChunkType.FORMULA,
}



@dataclass(frozen=True, slots=True)
class ChunkDraft:
    """A chunk decided but not yet given an identity.

    What a chunk *is* — its text, where it came from, what kind of thing it holds — is a
    question about the document. Which row it occupies and when it was written are
    questions about storage, and are answered by whoever persists it.
    """

    text: str
    token_count: int
    chunk_type: ChunkType
    heading_path: HeadingPath
    page_start: int
    page_end: int
    element_type: ElementType | None = None
    bounding_box: BoundingBox | None = None

    @property
    def chapter(self) -> str | None:
        segments = self.heading_path.segments
        return segments[0] if segments else None

    @property
    def section(self) -> str | None:
        segments = self.heading_path.segments
        return segments[1] if len(segments) > 1 else None


@dataclass(frozen=True, slots=True)
class ChunkFamily:
    """A passage and the smaller pieces it was cut into.

    The parent is a stretch of one section; the children are what a search matches inside
    it. They are produced together because the relationship is the point — a child on its
    own cannot say what it should expand to, and a parent on its own is too large to be
    matched precisely.
    """

    parent: ChunkDraft
    children: tuple[ChunkDraft, ...]


class Chunker:
    """Turn the elements of a document into section-bounded parents and their children."""

    def __init__(
        self,
        count_tokens: Callable[[str], int],
        *,
        target_tokens: int,
        max_tokens: int,
        overlap_tokens: int,
        parent_target_tokens: int,
        parent_max_tokens: int,
    ) -> None:
        require_positive(target_tokens, "target_tokens")
        require_positive(max_tokens, "max_tokens")
        require_positive(parent_target_tokens, "parent_target_tokens")
        require_positive(parent_max_tokens, "parent_max_tokens")
        if parent_target_tokens <= max_tokens:
            raise InvariantViolationError(
                "parent_target_tokens must exceed max_tokens — a parent no larger than "
                "the child ceiling restores no context the child did not already carry"
            )
        if parent_max_tokens < parent_target_tokens:
            raise InvariantViolationError(
                "parent_max_tokens must not be below parent_target_tokens"
            )
        self._count = count_tokens
        self._target = target_tokens
        self._max = max_tokens
        self._overlap = overlap_tokens
        self._parent_target = parent_target_tokens
        self._parent_max = parent_max_tokens

    def chunk(self, elements: Sequence[DocumentElement]) -> list[ChunkFamily]:
        """Every chunk the document yields, in reading order."""
        families: list[ChunkFamily] = []
        for section in _sections(elements):
            families.extend(self._chunk_section(section))
        return families

    # -----------------------------------------------------------------------

    def _chunk_section(self, section: Sequence[DocumentElement]) -> Iterator[ChunkFamily]:
        """Parents for one section, each with the children cut from it.

        A section too long to be one parent is divided within itself rather than being
        allowed to run on into the next one, so a parent is always a stretch of a single
        section and expansion never returns content from somewhere else.
        """
        for group in self._parent_groups(section):
            children = tuple(self._children(group))
            if not children:
                continue
            text = _join(group)
            parent = _draft_from(group, text, self._count(text), _kind_of(group))
            yield ChunkFamily(parent=parent, children=children)

    def _parent_groups(
        self, section: Sequence[DocumentElement]
    ) -> Iterator[list[DocumentElement]]:
        """Runs of elements large enough to be worth loading as context.

        Whole elements, because the children are cut from the same run: a parent built
        from a slice of text could fail to contain a child that began inside it, and a
        parent that does not contain its child expands to a passage the fragment is not
        in.
        """
        group: list[DocumentElement] = []
        for element in section:
            if not element.text.value.strip():
                continue
            if group and self._count(_join([*group, element])) > self._parent_max:
                yield group
                group = []
            group.append(element)
            if self._count(_join(group)) >= self._parent_target:
                yield group
                group = []
        if group:
            yield group

    def _children(self, group: Sequence[DocumentElement]) -> Iterator[ChunkDraft]:
        """The searchable pieces of one parent, which is as far as any of them may reach.

        Overlap stops at the parent boundary. A child carrying trailing text from the
        previous parent would not be contained by its own, and expansion would then hand
        back a passage that is missing the fragment it was asked to explain.
        """
        buffer: list[DocumentElement] = []

        for element in group:
            standalone = _STANDALONE.get(element.element_type)
            if standalone is not None:
                # Flush first, so the prose before a table stays before it rather than
                # being carried past it into whatever follows.
                yield from self._flush(buffer)
                buffer = []
                yield from self._standalone_drafts(element, standalone)
                continue

            if not element.text.value.strip():
                continue

            buffer.append(element)
            if self._tokens_in(buffer) >= self._target:
                yield from self._flush(buffer)
                buffer = self._carry_over(buffer)

        yield from self._flush(buffer)

    def _flush(self, buffer: Sequence[DocumentElement]) -> Iterator[ChunkDraft]:
        """Emit what has accumulated, splitting it further only if it grew too large."""
        if not buffer:
            return
        text = _join(buffer)
        if not text:
            return

        tokens = self._count(text)
        if tokens <= self._max:
            yield _draft_from(buffer, text, tokens, ChunkType.TEXT)
            return

        # Over the ceiling even as a single unit, so the paragraph level has failed and
        # sentences are the next boundary down.
        for piece in self._split_sentences(text):
            yield _draft_from(buffer, piece, self._count(piece), ChunkType.TEXT)

    def _standalone_drafts(
        self, element: DocumentElement, chunk_type: ChunkType
    ) -> Iterator[ChunkDraft]:
        """A table, figure or formula as its own chunk, split only if it must be.

        A figure carries no text at all, and a chunk of nothing is not retrievable, so it
        is skipped — the record that it exists lives on the element, and describing it is
        a later stage's work.
        """
        text = element.text.value.strip()
        if not text:
            return

        tokens = self._count(text)
        if tokens <= self._max:
            yield _draft_from([element], text, tokens, chunk_type)
            return

        # Too large to keep whole. Split on its own lines, which for a table are its
        # rows — the one boundary that does not cut a row in half.
        for piece in self._split_lines(text):
            yield _draft_from([element], piece, self._count(piece), chunk_type)

    def _carry_over(self, buffer: Sequence[DocumentElement]) -> list[DocumentElement]:
        """What the next chunk begins with, so a boundary is reachable from both sides.

        Whole elements rather than a slice of text: a paragraph is the smallest thing
        worth repeating, and carrying half of one would put a fragment at the head of the
        next chunk that reads as though it started there.
        """
        if self._overlap <= 0 or len(buffer) < 2:
            return []

        carried: list[DocumentElement] = []
        for element in reversed(buffer):
            if self._count(_join([element, *carried])) > self._overlap and carried:
                break
            carried.insert(0, element)
            if len(carried) == len(buffer):
                # Everything would carry over, which would make no progress at all.
                carried.pop(0)
                break
        return carried

    def _tokens_in(self, buffer: Sequence[DocumentElement]) -> int:
        return self._count(_join(buffer))

    def _split_sentences(self, text: str) -> list[str]:
        """Group sentences into pieces that fit, never breaking one in half."""
        return self._pack(split_sentences(text), joiner=" ")

    def _split_lines(self, text: str) -> list[str]:
        return self._pack(text.splitlines(), joiner="\n")

    def _pack(self, parts: Sequence[str], *, joiner: str) -> list[str]:
        """Fill pieces up to the ceiling, starting a new one rather than exceeding it.

        A single part larger than the ceiling is emitted whole. Splitting it further
        would mean cutting inside a sentence or a table row, and an oversized chunk that
        still says something is better than two that say half each.
        """
        pieces: list[str] = []
        current: list[str] = []
        for part in (p.strip() for p in parts):
            if not part:
                continue
            candidate = joiner.join([*current, part])
            if current and self._count(candidate) > self._max:
                pieces.append(joiner.join(current))
                current = [part]
            else:
                current.append(part)
        if current:
            pieces.append(joiner.join(current))
        return pieces


# ---------------------------------------------------------------------------
# Grouping and assembly
# ---------------------------------------------------------------------------


def _sections(elements: Sequence[DocumentElement]) -> Iterator[list[DocumentElement]]:
    """Runs of consecutive elements sharing a heading path.

    Consecutive rather than gathered: a document that returns to a section later — an
    appendix repeating a title, a running header — has two runs, and merging them would
    build a chunk out of pages that never sat together.
    """
    current: list[DocumentElement] = []
    path: HeadingPath | None = None
    for element in elements:
        if path is not None and element.heading_path != path:
            yield current
            current = []
        path = element.heading_path
        current.append(element)
    if current:
        yield current


def _join(elements: Sequence[DocumentElement]) -> str:
    """Elements as one passage, paragraphs separated as they were on the page."""
    return "\n\n".join(
        element.text.value.strip() for element in elements if element.text.value.strip()
    ).strip()


def _kind_of(elements: Sequence[DocumentElement]) -> ChunkType:
    """What a run of elements is, when it is all one thing.

    A section holding nothing but a table stays a table: calling it prose would hide it
    from anything asking for tables, and the run reads exactly as the table does.
    Anything mixed is prose, because no single kind describes it.
    """
    types = {element.element_type for element in elements}
    if len(types) == 1:
        return _STANDALONE.get(next(iter(types)), ChunkType.TEXT)
    return ChunkType.TEXT


def _draft_from(
    elements: Sequence[DocumentElement],
    text: str,
    tokens: int,
    chunk_type: ChunkType,
) -> ChunkDraft:
    pages = [element.page_number for element in elements]
    types = {element.element_type for element in elements}
    return ChunkDraft(
        text=text,
        token_count=max(1, tokens),
        chunk_type=chunk_type,
        heading_path=elements[0].heading_path,
        page_start=min(pages),
        page_end=max(pages),
        # Only when every element agrees. A chunk of mixed kinds has no single one.
        element_type=next(iter(types)) if len(types) == 1 else None,
        bounding_box=_merged_box(elements),
    )


def _merged_box(elements: Sequence[DocumentElement]) -> BoundingBox | None:
    """One box around the elements, when that means anything.

    Only for elements on a single page. A box spanning two pages describes a rectangle
    that exists on neither, and a citation opening at it would land nowhere.
    """
    if len({element.page_number for element in elements}) != 1:
        return None

    boxes = [element.bounding_box for element in elements if element.bounding_box]
    if not boxes:
        return None

    merged = boxes[0]
    for box in boxes[1:]:
        merged = merged.merged(box)
    return merged
