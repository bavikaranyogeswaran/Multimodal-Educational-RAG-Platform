"""Application dependency container.

Holds one instance of every port for the lifetime of the application. Built once
at startup by wire.build_container, stored in app.state.container, and provided
to request handlers through FastAPI dependencies.

Nothing outside this module and wire.py chooses which concrete adapter satisfies
which port. That authority belongs to the composition root alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.ports.adapters import (
    CacheStore,
    DenseRetriever,
    EmbeddingPort,
    GraphPort,
    KeywordRetriever,
    ObservabilityPort,
    OcrPort,
    PdfParserPort,
    RerankerPort,
    StoragePort,
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


@dataclass(frozen=True, slots=True)
class Container:
    """All port implementations, held for the application's lifetime.

    Each field is typed to the domain Protocol it satisfies. The only place
    that assigns these is wire.build_container; request handlers read them
    through FastAPI dependencies without knowing which adapter is behind each.
    """

    # Repository ports
    knowledge_base_repository: KnowledgeBaseRepository
    document_repository: DocumentRepository
    chunk_repository: ChunkRepository
    conversation_repository: ConversationRepository
    memory_repository: MemoryRepository
    graph_repository: GraphRepository
    job_repository: JobRepository

    # Adapter ports
    storage: StoragePort
    pdf_parser: PdfParserPort
    ocr: OcrPort
    embedder: EmbeddingPort
    reranker: RerankerPort
    dense_retriever: DenseRetriever
    keyword_retriever: KeywordRetriever
    graph: GraphPort
    cache: CacheStore
    observability: ObservabilityPort

    # Model gateway
    model_gateway: ModelGatewayPort
