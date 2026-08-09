"""Adapter wiring — the only place in the codebase that maps each domain port to
a concrete implementation.

Each implementation is added here when its phase lands. Until then, the slot
holds an _Unimplemented sentinel that raises NotImplementedError with a clear
message on first use, so a missing wire-up is not discovered as a silent null
or an opaque AttributeError somewhere deeper in the call chain.
"""

from __future__ import annotations

from typing import NoReturn, cast

from app.configuration.container import Container
from app.configuration.settings import Settings
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


class _Unimplemented:
    """Placeholder for an adapter that has not been wired yet.

    Raises NotImplementedError on any attribute access so a missing wire-up is
    discovered on first use rather than at import time or after a silent no-op.
    """

    def __init__(self, port_name: str) -> None:
        object.__setattr__(self, "_port_name", port_name)

    def __getattr__(self, name: str) -> NoReturn:
        port_name: str = object.__getattribute__(self, "_port_name")
        raise NotImplementedError(
            f"{port_name} has not been wired — add an adapter implementation "
            f"to app/configuration/wire.py before calling this method"
        )


def build_container(settings: Settings) -> Container:  # noqa: ARG001
    """Construct the application dependency container.

    settings is accepted now so call sites do not change when adapters arrive.
    Each adapter will receive the relevant settings sub-object as it is wired in.
    """

    def _u(name: str) -> _Unimplemented:
        return _Unimplemented(name)

    return Container(
        # Repository ports — wired in Phase 2 (SQLAlchemy adapters)
        knowledge_base_repository=cast(KnowledgeBaseRepository, _u("KnowledgeBaseRepository")),
        document_repository=cast(DocumentRepository, _u("DocumentRepository")),
        chunk_repository=cast(ChunkRepository, _u("ChunkRepository")),
        conversation_repository=cast(ConversationRepository, _u("ConversationRepository")),
        memory_repository=cast(MemoryRepository, _u("MemoryRepository")),
        graph_repository=cast(GraphRepository, _u("GraphRepository")),
        job_repository=cast(JobRepository, _u("JobRepository")),
        # Adapter ports — wired as their respective phases land
        storage=cast(StoragePort, _u("StoragePort")),
        pdf_parser=cast(PdfParserPort, _u("PdfParserPort")),
        ocr=cast(OcrPort, _u("OcrPort")),
        embedder=cast(EmbeddingPort, _u("EmbeddingPort")),
        reranker=cast(RerankerPort, _u("RerankerPort")),
        dense_retriever=cast(DenseRetriever, _u("DenseRetriever")),
        keyword_retriever=cast(KeywordRetriever, _u("KeywordRetriever")),
        graph=cast(GraphPort, _u("GraphPort")),
        cache=cast(CacheStore, _u("CacheStore")),
        observability=cast(ObservabilityPort, _u("ObservabilityPort")),
        # Model gateway — wired when the Ollama adapter is implemented
        model_gateway=cast(ModelGatewayPort, _u("ModelGatewayPort")),
    )
