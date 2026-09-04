"""Adapter wiring — the only place in the codebase that maps each domain port to
a concrete implementation.

Each implementation is added here when its phase lands. Until then, the slot
holds an _Unimplemented sentinel that raises NotImplementedError with a clear
message on first use, so a missing wire-up is not discovered as a silent null
or an opaque AttributeError somewhere deeper in the call chain.
"""

from __future__ import annotations

from typing import Any, NoReturn, cast

import httpx
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
from app.infrastructure.database.session import build_engine, build_session_factory
from app.infrastructure.memory.extractor import LlmMemoryExtractor
from app.infrastructure.memory.summarizer import LlmSummarizer
from app.infrastructure.models.gateway import ModelGatewayFacade
from app.infrastructure.models.providers.ollama import OllamaModelGateway
from app.infrastructure.models.providers.openai_compat import OpenAICompatibleGateway
from app.infrastructure.multi_hop.classifier import LlmQueryClassifier
from app.infrastructure.multi_hop.coverage import LlmCoverageClassifier
from app.infrastructure.multi_hop.decomposition import LlmQueryDecomposition
from app.infrastructure.multi_hop.synthesis import LlmMultiHopSynthesis
from app.infrastructure.rendering.figure_cropper import FigureCropper
from app.infrastructure.rendering.page_renderer import PageRenderer
from app.infrastructure.storage.r2 import build_r2_adapters
from app.infrastructure.tokenization.token_counter import HuggingFaceTokenCounter


def _build_model_gateway(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> ModelGatewayPort:
    from app.domain.enums import DataBoundary

    client = httpx.AsyncClient(base_url=settings.model.ollama_base_url)
    ollama = OllamaModelGateway(
        http_client=client,
        model_id=settings.model.default_text_model,
        timeout_seconds=settings.model.request_timeout_seconds,
    )
    providers: list[Any] = [ollama]

    oai_base_url = settings.model.openai_compatible_base_url
    if oai_base_url:
        oai_client = httpx.AsyncClient(base_url=oai_base_url)
        providers.append(
            OpenAICompatibleGateway(
                http_client=oai_client,
                model_id=settings.model.default_text_model,
                timeout_seconds=settings.model.request_timeout_seconds,
                data_boundary=DataBoundary.THIRD_PARTY,
                api_key=settings.model.openai_compatible_api_key.get_secret_value(),
            )
        )

    return ModelGatewayFacade(providers, session_factory=session_factory)


def _build_reranker(settings: Settings) -> RerankerPort:
    try:
        from app.infrastructure.reranking.cross_encoder import (
            CrossEncoderReranker,
        )

        return CrossEncoderReranker(
            model_id=settings.reranker.model_id,
            device=settings.reranker.device,
            batch_size=settings.reranker.batch_size,
        )
    except ImportError:
        return cast(RerankerPort, _Unimplemented("RerankerPort"))


def _build_pdf_parser(settings: Settings) -> PdfParserPort:
    try:
        from app.domain.documents.element_classifier import (
            ElementClassifier,
        )
        from app.domain.documents.page_classifier import PageClassifier
        from app.domain.documents.reading_order import (
            ReadingOrderResolver,
        )
        from app.infrastructure.parsing.pdfplumber_parser import (
            PdfPlumberParser,
        )

        return PdfPlumberParser(
            PageClassifier(
                min_native_characters=settings.ocr.min_native_characters,
                native_text_coverage_threshold=settings.ocr.native_text_coverage_threshold,
                image_coverage_threshold=settings.ocr.image_coverage_threshold,
                complex_vector_drawing_threshold=settings.ocr.complex_vector_drawing_threshold,
            ),
            ElementClassifier(
                heading_size_ratio=settings.parsing.heading_size_ratio,
                heading_max_lines=settings.parsing.heading_max_lines,
                formula_symbol_ratio=settings.parsing.formula_symbol_ratio,
            ),
            ReadingOrderResolver(
                min_gutter_width=settings.parsing.min_gutter_width,
                min_column_width=settings.parsing.min_column_width,
            ),
            paragraph_gap_multiplier=settings.parsing.paragraph_gap_multiplier,
            min_element_characters=settings.parsing.min_element_characters,
            min_gutter_width=settings.parsing.min_gutter_width,
        )
    except ImportError:
        return cast(PdfParserPort, _Unimplemented("PdfParserPort"))


def _build_ocr(settings: Settings) -> OcrPort:
    try:
        from app.infrastructure.ocr.fallback import FallbackOcrAdapter
        from app.infrastructure.ocr.paddle_ocr import PaddleOcrAdapter

        primary: OcrPort = PaddleOcrAdapter(
            lang=settings.ocr.language,
            dpi=settings.storage.page_render_dpi,
        )

        secondary: OcrPort | None = None
        if settings.ocr.vl_fallback_enabled:
            try:
                from app.infrastructure.ocr.paddle_ocr_vl import PaddleOcrVlAdapter

                secondary = PaddleOcrVlAdapter(
                    lang=settings.ocr.language,
                    dpi=settings.storage.page_render_dpi,
                )
            except ImportError:
                pass

        return FallbackOcrAdapter(
            primary=primary,
            secondary=secondary,
            confidence_threshold=settings.ocr.vl_confidence_threshold,
        )
    except ImportError:
        pass

    try:
        from app.infrastructure.ocr.tesseract import TesseractAdapter

        return TesseractAdapter(
            lang=settings.ocr.language,
            dpi=settings.storage.page_render_dpi,
        )
    except ImportError:
        return cast(OcrPort, _Unimplemented("OcrPort"))


def _build_token_counter(settings: Settings) -> TokenCounterPort:
    """Built eagerly, and allowed to fail.

    Unlike the adapters around it there is no `_Unimplemented` fallback: a counter that
    silently estimated would size every chunk wrongly and nothing downstream would show
    it. Failing at startup is the only honest option.
    """
    return HuggingFaceTokenCounter(
        model_id=settings.embedding.model_id,
        max_input_tokens=settings.embedding.max_input_tokens,
    )


def _build_embedder(settings: Settings) -> EmbeddingPort:
    try:
        from app.infrastructure.embeddings.sentence_transformer import (
            SentenceTransformerEmbedder,
        )

        return SentenceTransformerEmbedder(
            model_id=settings.embedding.model_id,
            device=settings.embedding.device,
            batch_size=settings.embedding.batch_size,
        )
    except ImportError:
        return cast(EmbeddingPort, _Unimplemented("EmbeddingPort"))


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
    _figure_cropper: FigureCropper | None
    if settings.storage.account_id:
        _storage, _cache = build_r2_adapters(settings.storage)
        _figure_cropper = FigureCropper(dpi=settings.storage.page_render_dpi)
    else:
        _storage = cast(StoragePort, _u("StoragePort"))
        _cache = cast(CacheStore, _u("CacheStore"))
        _figure_cropper = None

    _gw = _build_model_gateway(
        settings,
        session_factory=_session_factory if db_url else None,
    )

    return Container(
        session_factory=_session_factory,
        page_renderer=PageRenderer(
            _cache,
            dpi=settings.storage.page_render_dpi,
            ttl_seconds=settings.storage.page_render_ttl_seconds,
        ),
        figure_cropper=_figure_cropper,
        # Memory adapters
        memory_extractor=LlmMemoryExtractor(_gw),
        summarizer=LlmSummarizer(_gw),
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
        pdf_parser=_build_pdf_parser(settings),
        ocr=_build_ocr(settings),
        embedder=_build_embedder(settings),
        token_counter=_build_token_counter(settings),
        reranker=_build_reranker(settings),
        dense_retriever=cast(DenseRetriever, _u("DenseRetriever")),
        keyword_retriever=cast(KeywordRetriever, _u("KeywordRetriever")),
        # Left empty on purpose — graph traversal runs against PostgreSQL through the
        # repository, so nothing asks for this. Kept as the seam a graph database would
        # arrive through; see the note on the Container field.
        graph=cast(GraphPort, _u("GraphPort")),
        observability=cast(ObservabilityPort, _u("ObservabilityPort")),
        # Model gateway — shared with all model-backed adapters
        model_gateway=_gw,
        # Query routing and multi-hop adapters
        query_classifier=LlmQueryClassifier(_gw),
        query_decomposition=LlmQueryDecomposition(_gw),
        coverage_classifier=LlmCoverageClassifier(_gw),
        multi_hop_synthesis=LlmMultiHopSynthesis(_gw),
    )
