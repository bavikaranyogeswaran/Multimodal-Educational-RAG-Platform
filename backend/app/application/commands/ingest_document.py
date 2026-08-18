"""Use case: ingest a document that has already been uploaded and stored in R2.

Receives a Document entity that is already in PROCESSING state. Downloads the bytes from
object storage, parses them into pages and layout elements, persists both, splits the
text into overlapping chunks, generates dense embeddings, and persists those. Returns the
document in COMPLETED state — the caller is responsible for saving it and committing.

Pages and elements are written before chunking begins. They are what the parse actually
established, and they stay useful whether or not the stages after them succeed: a page
recorded as needing recognition is a fact worth keeping even if this run then fails.

Chunking still consumes page text rather than the elements directly. Rewriting the
splitter to work over structure is worth doing once, after the parser can tell a heading
from a paragraph — doing it now would mean writing it twice.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.documents.chunks import Chunk
from app.domain.documents.entities import Document, DocumentElement, DocumentPage
from app.domain.enums import ChunkType
from app.domain.ports.adapters import (
    EmbeddingPort,
    PdfParserPort,
    StoragePort,
    TokenCounterPort,
)
from app.domain.ports.repositories import ChunkRepository, DocumentRepository
from app.domain.scope import ScopeContext
from app.domain.values import HeadingPath, UntrustedText

# (1-indexed page number, text for that page)
PageText = tuple[int, str]
ParsedPage = tuple[DocumentPage, Sequence[DocumentElement]]


@dataclass(frozen=True)
class IngestDocumentCommand:
    scope: ScopeContext
    document: Document


class IngestDocumentUseCase:
    """Download → chunk → embed → persist.

    The caller (worker) is responsible for:
    - ensuring the document is in PROCESSING state before calling execute
    - saving the returned COMPLETED document
    - marking the job as COMPLETED
    - catching exceptions and transitioning both the document and job to FAILED
    """

    def __init__(
        self,
        chunk_repo: ChunkRepository,
        document_repo: DocumentRepository,
        storage: StoragePort,
        embedder: EmbeddingPort,
        *,
        parser: PdfParserPort,
        token_counter: TokenCounterPort,
        embedding_model_id: str,
        index_version: int,
        chunk_chars: int,
        chunk_overlap_chars: int,
    ) -> None:
        self._chunk_repo = chunk_repo
        self._document_repo = document_repo
        self._storage = storage
        self._embedder = embedder
        self._parser = parser
        self._token_counter = token_counter
        self._embedding_model_id = embedding_model_id
        self._index_version = index_version
        self._chunk_chars = chunk_chars
        self._chunk_overlap_chars = chunk_overlap_chars

    async def execute(self, command: IngestDocumentCommand) -> Document:
        scope = command.scope
        doc = command.document
        now = datetime.now(UTC)

        # Download the original file from object storage
        data = await self._storage.get(doc.storage_key)

        # Parse into pages and layout elements. Pages whose text layer cannot be
        # trusted come back with no elements rather than with a partial reading.
        parsed = await self._parser.parse(data, document_id=doc.id, scope=scope)

        # Persisted before chunking, because they are what the parse established and
        # they remain true regardless of what the later stages do.
        await self._document_repo.save_pages(scope, [page for page, _ in parsed])
        elements = [element for _, page_elements in parsed for element in page_elements]
        if elements:
            await self._document_repo.save_elements(scope, elements)

        # Build chunks from the text the parse recovered
        chunks = _build_chunks(
            _page_texts(parsed),
            doc=doc,
            scope=scope,
            chunk_chars=self._chunk_chars,
            overlap_chars=self._chunk_overlap_chars,
            index_version=self._index_version,
            now=now,
            count_tokens=self._token_counter.count,
        )

        if chunks:
            # Persist chunks (without embeddings) first so the DB row exists
            # before we write the embedding vector to it.
            await self._chunk_repo.save_batch(scope, chunks)

            # Generate embeddings for all chunk texts in one batched call
            texts = [c.text.value for c in chunks]
            vectors = await self._embedder.embed_documents(texts)

            await self._chunk_repo.set_embeddings(
                scope,
                {c.id: v for c, v in zip(chunks, vectors, strict=True)},
                model_id=self._embedding_model_id,
                dimension=self._embedder.dimension,
                version=self._index_version,
            )

        # The parse counted the pages, so the count is known rather than inferred from
        # whichever page happened to yield text last.
        return doc.mark_completed(page_count=len(parsed), now=now)


# ---------------------------------------------------------------------------
# Chunking helpers
# ---------------------------------------------------------------------------


def _page_texts(parsed: Sequence[ParsedPage]) -> list[PageText]:
    """Flatten each page's elements back to text, in reading order.

    The bridge between a parser that produces structure and a splitter that does not use
    it yet. Paragraphs are joined with a blank line rather than a space so the boundaries
    survive in the text, ready for the splitter that will eventually respect them.
    """
    return [
        (page.page_number, "\n\n".join(element.text.value for element in elements))
        for page, elements in parsed
        if elements
    ]


def _build_chunks(
    pages: Sequence[PageText],
    *,
    doc: Document,
    scope: ScopeContext,
    chunk_chars: int,
    overlap_chars: int,
    index_version: int,
    now: datetime,
    count_tokens: Callable[[str], int],
) -> list[Chunk]:
    chunks: list[Chunk] = []
    ordinal = 0
    for page_num, page_text in pages:
        if not page_text.strip():
            continue
        for segment in _split_text(page_text, chunk_chars, overlap_chars):
            if not segment.strip():
                continue
            # Counted with the embedding model's own vocabulary rather than estimated
            # from length. The two agree on ordinary prose and diverge badly on dense
            # material — formulae and table rows run to roughly twice what a
            # character estimate predicts, which is how a chunk sized to fit arrives
            # over the model's limit and loses its tail.
            token_estimate = max(1, count_tokens(segment))
            chunks.append(
                Chunk(
                    id=uuid4(),
                    user_id=scope.user_id,
                    knowledge_base_id=scope.knowledge_base_id,
                    document_id=doc.id,
                    chunk_type=ChunkType.TEXT,
                    text=UntrustedText(segment),
                    token_count=token_estimate,
                    ordinal=ordinal,
                    page_start=page_num,
                    page_end=page_num,
                    index_version=index_version,
                    created_at=now,
                    language=doc.language,
                    content_hash=hashlib.sha256(segment.encode()).hexdigest(),
                    heading_path=HeadingPath.root(),
                )
            )
            ordinal += 1
    return chunks


def _split_text(text: str, chunk_chars: int, overlap_chars: int) -> list[str]:
    """Split text into overlapping windows of at most chunk_chars characters."""
    if len(text) <= chunk_chars:
        return [text]
    segments: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        # Absorb a tiny tail into the current chunk rather than emitting a
        # separate segment smaller than the overlap window.
        if len(text) - end <= overlap_chars:
            end = len(text)
        segments.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap_chars
    return segments
