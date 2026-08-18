"""Adapter ports — the infrastructure interfaces the domain depends on.

These are the driven (outbound) ports for everything that is not persistence: object
storage, document parsing, OCR, embeddings, reranking, retrieval, graph traversal,
caching, and observability. Infrastructure adapters implement them by structural
subtyping without importing this module.

Scope enforcement:
  - Methods that query or write scoped data carry `ScopeContext` as their first
    parameter (`DenseRetriever`, `KeywordRetriever`, `GraphPort`, `PdfParserPort`).
  - Pure-computation adapters (`EmbeddingPort`, `RerankerPort`) receive no scope —
    they transform data rather than access it.
  - Key-based adapters (`StoragePort`, `CacheStore`) embed scope in the key; passing
    it separately would only add a redundant parameter with no enforcement value.
  - `OcrPort` receives the page object, which already carries the scope needed to
    produce correctly-scoped `DocumentElement` outputs.
  - `ObservabilityPort` is a system-level concern that operates outside user scope.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol
from uuid import UUID

from app.domain.documents.entities import DocumentElement, DocumentPage
from app.domain.graph.entities import GraphEntity, GraphRelationship
from app.domain.retrieval.entities import Evidence, RetrievalFilters
from app.domain.scope import ScopeContext

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class StoragePort(Protocol):
    """Object storage for documents, crops, and exports (Cloudflare R2 or equivalent).

    Keys encode the scope: callers use `{user_id}/{kb_id}/...` prefixes so no
    cross-user access can happen silently. Blobs are never listed without an
    explicit prefix that carries the scope.
    """

    async def put(self, key: str, data: bytes, *, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def presigned_get_url(self, key: str, *, expires_in: int) -> str:
        """A time-limited URL for direct client download.

        `expires_in` is in seconds. The URL must not outlive the scope under which
        the document was uploaded.
        """
        ...


# ---------------------------------------------------------------------------
# Document processing
# ---------------------------------------------------------------------------


class PdfParserPort(Protocol):
    """Layout-aware PDF parser.

    The parser determines how each page must be read (native text, scanned, or
    mixed) and extracts all text elements it can reach without OCR. Pages flagged
    as SCANNED or COMPLEX come back with an empty element list; the OCR stage fills
    them in separately.
    """

    async def parse(
        self,
        data: bytes,
        *,
        document_id: UUID,
        scope: ScopeContext,
    ) -> Sequence[tuple[DocumentPage, Sequence[DocumentElement]]]:
        """Parse a PDF and return one pair per page.

        Each pair contains the page (with its kind and dimensions) and any elements
        extractable without OCR. SCANNED and COMPLEX pages return an empty element
        sequence; the caller passes those pages to `OcrPort`.
        """
        ...


class PageRendererPort(Protocol):
    """Draws pages to images, and forgets them again.

    Renders are regenerable, so they live in a cache with a lifetime rather than in
    permanent storage. That makes forgetting them a real operation rather than an
    afterthought: a document being deleted has cached images that outlive it otherwise,
    and nothing about their keys would ever say they no longer refer to anything.
    """

    async def render(
        self,
        data: bytes,
        *,
        page_number: int,
        document_id: UUID,
        scope: ScopeContext,
    ) -> bytes:
        """PNG bytes for one page, 1-indexed, from the cache when already drawn."""
        ...

    async def discard_document(
        self,
        *,
        document_id: UUID,
        scope: ScopeContext,
        page_count: int,
    ) -> None:
        """Forget every cached render belonging to a document.

        The page count comes from the caller because the document knows it and this does
        not. Passing it keeps the renderer from having to query anything to do its job.
        """
        ...


class OcrPort(Protocol):
    """Optical character recognition over rendered page images.

    Receives the page object so that returned elements inherit the correct scope,
    document ID, and page number without the adapter having to manage them.
    """

    async def extract_text(
        self,
        image: bytes,
        *,
        page: DocumentPage,
    ) -> Sequence[DocumentElement]:
        """Extract text elements from a rendered page image.

        `image` is a PNG or JPEG byte string rendered at the caller's chosen DPI.
        Every returned element is already scoped to `page`'s user and Knowledge Base.
        """
        ...


# ---------------------------------------------------------------------------
# Embeddings and reranking
# ---------------------------------------------------------------------------


class EmbeddingPort(Protocol):
    """Dense embedding model.

    Document and query embeddings use separate methods because some models apply
    different instruction prefixes or pooling strategies to each.
    """

    @property
    def dimension(self) -> int:
        """The length of every vector this model produces."""
        ...

    async def embed_documents(
        self, texts: Sequence[str]
    ) -> Sequence[Sequence[float]]:
        """Embed a batch of document passages, returning one vector per input."""
        ...

    async def embed_query(self, text: str) -> Sequence[float]:
        """Embed a single search query."""
        ...


class TokenCounterPort(Protocol):
    """Counts text in the units the embedding model works in.

    Synchronous, unlike every other port here, because it is a calculation rather than a
    journey anywhere. Making it async would put an await in front of arithmetic and force
    the chunker — which is otherwise pure — to become async to reach it.
    """

    @property
    def max_input_tokens(self) -> int:
        """The most the model will read before it starts discarding the end."""
        ...

    def count(self, text: str) -> int:
        """Tokens in `text`, excluding the markers the model adds around an input."""
        ...

    def fits(self, text: str) -> bool:
        """Whether `text` would reach the model whole rather than truncated."""
        ...


class RerankerPort(Protocol):
    """Cross-encoder reranker.

    Returns a relevance score per candidate in the same order they were supplied.
    Higher scores indicate more relevant candidates. Scores are not on a fixed scale
    — downstream code uses them for relative ordering, not absolute thresholds.
    """

    async def rerank(
        self,
        query: str,
        candidates: Sequence[str],
    ) -> Sequence[float]:
        """Score each candidate against the query. Order matches `candidates`."""
        ...


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


class DenseRetriever(Protocol):
    """Vector similarity search over chunk embeddings."""

    async def search(
        self,
        scope: ScopeContext,
        query_embedding: Sequence[float],
        *,
        top_k: int,
        filters: RetrievalFilters,
    ) -> Sequence[Evidence]:
        """Return up to `top_k` evidence items ordered by descending similarity."""
        ...


class KeywordRetriever(Protocol):
    """Full-text keyword search using PostgreSQL RUM indexes."""

    async def search(
        self,
        scope: ScopeContext,
        query: str,
        *,
        top_k: int,
        filters: RetrievalFilters,
    ) -> Sequence[Evidence]:
        """Return up to `top_k` evidence items ordered by descending rank score."""
        ...


class GraphPort(Protocol):
    """Graph traversal in vocabulary terms, never in a query language.

    The vocabulary (`neighbors`, `subgraph`) is what keeps the graph store
    swappable: a caller that asks for neighbours cannot depend on Cypher, SPARQL,
    or any specific traversal API, so a different backend is a different adapter,
    not a different set of callers.
    """

    async def neighbors(
        self,
        scope: ScopeContext,
        entity_id: UUID,
        *,
        max_hops: int = 1,
    ) -> Sequence[GraphEntity]:
        """Entities reachable from `entity_id` within `max_hops` steps."""
        ...

    async def subgraph(
        self,
        scope: ScopeContext,
        entity_ids: frozenset[UUID],
        *,
        max_nodes: int,
    ) -> tuple[Sequence[GraphEntity], Sequence[GraphRelationship]]:
        """The induced subgraph for a set of seed entities, capped at `max_nodes`."""
        ...


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class CacheStore(Protocol):
    """Short-lived byte cache for regenerable content (page renders, computed crops).

    Keys are caller-controlled. The `ttl` on writes keeps stale bytes from
    accumulating; there is no notification when an entry expires.
    """

    async def get(self, key: str) -> bytes | None: ...

    async def put(self, key: str, data: bytes, *, ttl: int) -> None:
        """Store with a TTL in seconds."""
        ...

    async def delete(self, key: str) -> None: ...


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


class ObservabilityPort(Protocol):
    """Structured event emission for pipeline tracing and timing.

    The application layer calls this to record stage completions and attach
    trace-level metadata. Implementations write to structlog, an OTLP exporter,
    or both. Methods are synchronous because logging must not add await points
    inside a pipeline stage.
    """

    def emit(
        self,
        event: str,
        *,
        attributes: Mapping[str, object],
    ) -> None:
        """Emit a named event with structured key-value attributes."""
        ...

    def child(self, **bindings: object) -> ObservabilityPort:
        """Return a child context with additional key-value pairs bound to every event.

        Used to attach a trace ID or request ID once at the start of a use case,
        so callers do not thread it through every subsequent call.
        """
        ...
