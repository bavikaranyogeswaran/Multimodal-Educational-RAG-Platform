"""Adapter wiring — the only place in the codebase that maps each domain port to
a concrete implementation.

Each implementation is added here when its phase lands. Until then, the slot
holds an _Unimplemented sentinel that raises NotImplementedError with a clear
message on first use, so a missing wire-up is not discovered as a silent null
or an opaque AttributeError somewhere deeper in the call chain.
"""

from __future__ import annotations

from typing import NoReturn, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from app.infrastructure.database.session import build_engine, build_session_factory
from app.infrastructure.storage.r2 import build_r2_adapters


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


def build_container(settings: Settings) -> Container:
    """Construct the application dependency container.

    The async engine and session factory are built here from database settings
    and stored on the Container. If no DATABASE_URL is configured (local dev
    without a database), a stub factory is placed in the slot so the Container
    still constructs; the stub raises NotImplementedError on first use.
    """

    def _u(name: str) -> _Unimplemented:
        return _Unimplemented(name)

    db_url = settings.database.url.get_secret_value()
    if db_url:
        _session_factory: async_sessionmaker[AsyncSession] = build_session_factory(
            build_engine(settings.database)
        )
    else:
        _session_factory = cast(async_sessionmaker[AsyncSession], _u("SessionFactory"))

    _storage: StoragePort
    _cache: CacheStore
    if settings.storage.account_id:
        _storage, _cache = build_r2_adapters(settings.storage)
    else:
        _storage = cast(StoragePort, _u("StoragePort"))
        _cache = cast(CacheStore, _u("CacheStore"))

    return Container(
        session_factory=_session_factory,
        # Repository ports — wired in Phase 2 (SQLAlchemy adapters)
        knowledge_base_repository=cast(KnowledgeBaseRepository, _u("KnowledgeBaseRepository")),
        document_repository=cast(DocumentRepository, _u("DocumentRepository")),
        chunk_repository=cast(ChunkRepository, _u("ChunkRepository")),
        conversation_repository=cast(ConversationRepository, _u("ConversationRepository")),
        memory_repository=cast(MemoryRepository, _u("MemoryRepository")),
        graph_repository=cast(GraphRepository, _u("GraphRepository")),
        job_repository=cast(JobRepository, _u("JobRepository")),
        # Adapter ports — wired as their respective phases land
        storage=_storage,
        cache=_cache,
        pdf_parser=cast(PdfParserPort, _u("PdfParserPort")),
        ocr=cast(OcrPort, _u("OcrPort")),
        embedder=cast(EmbeddingPort, _u("EmbeddingPort")),
        reranker=cast(RerankerPort, _u("RerankerPort")),
        dense_retriever=cast(DenseRetriever, _u("DenseRetriever")),
        keyword_retriever=cast(KeywordRetriever, _u("KeywordRetriever")),
        graph=cast(GraphPort, _u("GraphPort")),
        observability=cast(ObservabilityPort, _u("ObservabilityPort")),
        # Model gateway — wired when the Ollama adapter is implemented
        model_gateway=cast(ModelGatewayPort, _u("ModelGatewayPort")),
    )
