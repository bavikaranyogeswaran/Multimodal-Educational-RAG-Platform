"""Chunks — the unit retrieval actually searches.

Chunking is hierarchical: small children are searched because precision improves when the
match is not diluted, and a larger parent is loaded only when the child turns out to be
incomplete on its own. Both are chunks; a child names its parent, a parent names nobody.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from uuid import UUID

from app.domain.enums import ChunkType, ElementType
from app.domain.errors import InvariantViolationError
from app.domain.invariants import (
    require_non_negative,
    require_positive,
    require_timezone_aware,
)
from app.domain.scope import ScopeContext
from app.domain.values import BoundingBox, HeadingPath, UntrustedText


@dataclass(frozen=True, slots=True)
class Chunk:
    """A retrievable passage, with enough context to be presented rather than dumped.

    The metadata is not decoration. Heading path is what lets a retrieved fragment be
    shown as part of a section instead of as an orphaned paragraph; the page range and
    bounding box are what make it possible to open the source at the right place; the
    index version is what stops a query mixing embeddings from two different models.
    """

    id: UUID
    user_id: UUID
    knowledge_base_id: UUID
    document_id: UUID
    chunk_type: ChunkType
    text: UntrustedText
    token_count: int
    ordinal: int
    page_start: int
    page_end: int
    index_version: int
    created_at: datetime

    parent_chunk_id: UUID | None = None
    source_element_id: UUID | None = None
    chapter: str | None = None
    section: str | None = None
    heading_path: HeadingPath = field(default_factory=HeadingPath.root)
    element_type: ElementType | None = None
    bounding_box: BoundingBox | None = None
    language: str = "en"
    content_hash: str | None = None

    def __post_init__(self) -> None:
        require_positive(self.token_count, "Chunk.token_count")
        require_non_negative(self.ordinal, "Chunk.ordinal")
        require_positive(self.page_start, "Chunk.page_start")
        require_positive(self.page_end, "Chunk.page_end")
        require_positive(self.index_version, "Chunk.index_version")
        require_timezone_aware(self.created_at, "Chunk.created_at")

        if self.page_end < self.page_start:
            raise InvariantViolationError(
                f"Chunk.page_end ({self.page_end}) precedes page_start ({self.page_start})"
            )
        if self.parent_chunk_id == self.id:
            raise InvariantViolationError("a Chunk cannot be its own parent")
        if self.text.is_blank():
            raise InvariantViolationError("Chunk.text must not be blank")

    @property
    def scope(self) -> ScopeContext:
        return ScopeContext(user_id=self.user_id, knowledge_base_id=self.knowledge_base_id)

    @property
    def is_child(self) -> bool:
        """Children are what retrieval searches; parents are what expansion loads."""
        return self.parent_chunk_id is not None

    @property
    def is_parent(self) -> bool:
        return self.parent_chunk_id is None

    @property
    def spans_pages(self) -> bool:
        return self.page_end > self.page_start

    @property
    def page_span(self) -> range:
        return range(self.page_start, self.page_end + 1)

    @property
    def is_text(self) -> bool:
        return self.chunk_type is ChunkType.TEXT

    @property
    def carries_a_visual(self) -> bool:
        """Whether answering from this chunk needs the original image rather than the text.

        A stored description of a figure is derived, not authoritative — a visual question
        gets the real crop.
        """
        return self.chunk_type in {
            ChunkType.FIGURE,
            ChunkType.CHART,
            ChunkType.DIAGRAM,
        }

    def with_compressed_text(self, text: UntrustedText) -> Chunk:
        """A narrowed copy, after extractive compression has selected the relevant part.

        Token count is not recomputed here — the caller knows the tokenizer, and guessing
        would put a wrong number into the context builder's budget.
        """
        if text.is_blank():
            raise InvariantViolationError("compressed text must not be blank")
        if len(text) > len(self.text):
            raise InvariantViolationError("compression must not lengthen the text")
        return replace(self, text=text)
