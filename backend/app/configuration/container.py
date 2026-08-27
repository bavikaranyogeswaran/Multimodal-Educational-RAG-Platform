"""Application dependency container.

Holds one instance of every port for the lifetime of the application. Built once
at startup by wire.build_container, stored in app.state.container, and provided
to request handlers through FastAPI dependencies.

Nothing outside this module and wire.py chooses which concrete adapter satisfies
which port. That authority belongs to the composition root alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.ports.adapters import (
    CacheStore,
    DenseRetriever,
    EmbeddingPort,
    FigureCropperPort,
    GraphPort,
    KeywordRetriever,
    MemoryExtractionPort,
    ObservabilityPort,
    OcrPort,
    PdfParserPort,
    RerankerPort,
    StoragePort,
    TokenCounterPort,
)
from app.domain.ports.model_gateway import ModelGatewayPort
from app.domain.ports.repositories import (
    ChunkRepository,
    ConversationRepository,
    DocumentRepository,
    GraphRepository,
    JobRepository,
    KnowledgeBaseRepository,
    MemoryRepository,
)
from app.infrastructure.rendering.page_renderer import PageRenderer


@dataclass(frozen=True, slots=True)
class Container:
    """All port implementations, held for the application's lifetime.

    Each field is typed to the domain Protocol it satisfies. The only place
    that assigns these is wire.build_container; request handlers read them
    through FastAPI dependencies without knowing which adapter is behind each.
    """

    # Infrastructure — not a domain port; owns the database connection pool
    session_factory: async_sessionmaker[AsyncSession]

    # Infrastructure — no domain port yet. Nothing in the application layer renders
    # a page; the recognition stage that will is not built. A port invented before
    # its caller exists would be a guess at the signature that caller wants.
    page_renderer: PageRenderer

    # Figure cropping — wired when R2 is configured (step 6.5)
    figure_cropper: FigureCropperPort | None

    # Repository ports
    knowledge_base_repository: KnowledgeBaseRepository
    document_repository: DocumentRepository
    chunk_repository: ChunkRepository
    conversation_repository: ConversationRepository
    memory_repository: MemoryRepository
    graph_repository: GraphRepository
    job_repository: JobRepository

    # Memory extraction — None until the LLM extractor adapter is implemented
    memory_extractor: MemoryExtractionPort | None

    # Adapter ports
    storage: StoragePort
    pdf_parser: PdfParserPort
    ocr: OcrPort
    embedder: EmbeddingPort
    token_counter: TokenCounterPort
    reranker: RerankerPort
    dense_retriever: DenseRetriever
    keyword_retriever: KeywordRetriever
    graph: GraphPort
    cache: CacheStore
    observability: ObservabilityPort

    # Model gateway
    model_gateway: ModelGatewayPort
