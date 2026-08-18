"""Use case: ingest a document that has already been uploaded and stored in R2.

Receives a Document entity that is already in PROCESSING state. Downloads the bytes from
object storage, parses them into pages and layout elements, persists both, splits the
elements into overlapping chunks, generates dense embeddings, and persists those. Returns
the document in COMPLETED state — the caller is responsible for saving it and committing.

Pages and elements are written before chunking begins. They are what the parse actually
established, and they stay useful whether or not the stages after them succeed: a page
recorded as needing recognition is a fact worth keeping even if this run then fails.

Chunking works from the elements rather than from flattened page text, so the boundaries
it places are the document's own — a section ends, a paragraph ends — rather than a
character count arriving mid-word. Deciding where those boundaries go is a rule, and
lives in the domain; this use case supplies the elements and gives the results identities.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.documents.chunker import ChunkDraft, Chunker
from app.domain.documents.chunks import Chunk
from app.domain.documents.entities import Document, DocumentElement, DocumentPage
from app.domain.ports.adapters import EmbeddingPort, PdfParserPort, StoragePort
from app.domain.ports.repositories import ChunkRepository, DocumentRepository
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText

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
        chunker: Chunker,
        embedding_model_id: str,
        index_version: int,
    ) -> None:
        self._chunk_repo = chunk_repo
        self._document_repo = document_repo
        self._storage = storage
        self._embedder = embedder
        self._parser = parser
        self._chunker = chunker
        self._embedding_model_id = embedding_model_id
        self._index_version = index_version

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

        chunks = _to_chunks(
            self._chunker.chunk(elements),
            doc=doc,
            scope=scope,
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

        # The parse counted the pages, so the count is known rather than inferred from
        # whichever page happened to yield text last.
        return doc.mark_completed(page_count=len(parsed), now=now)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _to_chunks(
    drafts: Sequence[ChunkDraft],
    *,
    doc: Document,
    scope: ScopeContext,
    index_version: int,
    now: datetime,
) -> list[Chunk]:
    """Give each decided chunk an identity and the attributes storage needs.

    The chunker settled what the chunks are. Everything added here — an id, a position
    in the document, which index version produced it — is about keeping them rather than
    about the document they came from.
    """
    return [
        Chunk(
            id=uuid4(),
            user_id=scope.user_id,
            knowledge_base_id=scope.knowledge_base_id,
            document_id=doc.id,
            chunk_type=draft.chunk_type,
            text=UntrustedText(draft.text),
            token_count=draft.token_count,
            ordinal=ordinal,
            page_start=draft.page_start,
            page_end=draft.page_end,
            index_version=index_version,
            created_at=now,
            language=doc.language,
            content_hash=hashlib.sha256(draft.text.encode()).hexdigest(),
            heading_path=draft.heading_path,
            chapter=draft.chapter,
            section=draft.section,
            element_type=draft.element_type,
            bounding_box=draft.bounding_box,
        )
        for ordinal, draft in enumerate(drafts)
    ]
