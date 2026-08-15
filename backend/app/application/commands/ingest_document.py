"""Use case: ingest a document that has already been uploaded and stored in R2.

Receives a Document entity that is already in PROCESSING state. Downloads the
bytes from object storage, extracts text page by page, splits into overlapping
chunks, generates dense embeddings, and persists everything. Returns the
document in COMPLETED state — the caller is responsible for saving it and
committing the session.

PDF parsing is injected as a callable so the application layer stays free of
third-party library imports.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.documents.chunks import Chunk
from app.domain.documents.entities import Document
from app.domain.enums import ChunkType
from app.domain.ports.adapters import EmbeddingPort, StoragePort
from app.domain.ports.repositories import ChunkRepository
from app.domain.scope import ScopeContext
from app.domain.values import HeadingPath, UntrustedText

# (1-indexed page number, extracted text for that page)
PageText = tuple[int, str]


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
        storage: StoragePort,
        embedder: EmbeddingPort,
        *,
        pdf_page_extractor: Callable[[bytes], Sequence[PageText]],
        embedding_model_id: str,
        index_version: int,
        chunk_chars: int,
        chunk_overlap_chars: int,
    ) -> None:
        self._chunk_repo = chunk_repo
        self._storage = storage
        self._embedder = embedder
        self._extractor = pdf_page_extractor
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

        # Extract text page by page (may return empty for scanned-only PDFs)
        pages: Sequence[PageText] = self._extractor(data)

        # Build chunks from the extracted pages
        chunks = _build_chunks(
            pages,
            doc=doc,
            scope=scope,
            chunk_chars=self._chunk_chars,
            overlap_chars=self._chunk_overlap_chars,
            index_version=self._index_version,
            now=now,
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

        page_count = doc.page_count or (max(p for p, _ in pages) if pages else 1)
        return doc.mark_completed(page_count=page_count, now=now)


# ---------------------------------------------------------------------------
# Chunking helpers
# ---------------------------------------------------------------------------


def _build_chunks(
    pages: Sequence[PageText],
    *,
    doc: Document,
    scope: ScopeContext,
    chunk_chars: int,
    overlap_chars: int,
    index_version: int,
    now: datetime,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    ordinal = 0
    for page_num, page_text in pages:
        if not page_text.strip():
            continue
        for segment in _split_text(page_text, chunk_chars, overlap_chars):
            if not segment.strip():
                continue
            token_estimate = max(1, len(segment) // 4)
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
