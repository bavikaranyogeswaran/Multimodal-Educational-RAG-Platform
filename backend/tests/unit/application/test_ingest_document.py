"""Unit tests for IngestDocumentUseCase.

All I/O (storage, embedder, chunk repository) is mocked. The extractor is a
simple lambda so tests do not depend on pypdf.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from app.application.commands.ingest_document import (
    IngestDocumentCommand,
    IngestDocumentUseCase,
    _split_text,
)
from app.domain.documents.entities import Document
from app.domain.enums import DocumentStatus
from app.domain.scope import ScopeContext

_NOW = datetime(2025, 1, 15, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_DOC_ID = uuid.uuid4()
_STORAGE_KEY = f"{_USER_ID}/{_KB_ID}/{_DOC_ID}/original.pdf"

_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)

_FAKE_VECTOR = [0.1] * 384


def _make_doc(*, status: DocumentStatus = DocumentStatus.PROCESSING) -> Document:
    return Document(
        id=_DOC_ID,
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        filename="lecture.pdf",
        content_type="application/pdf",
        byte_size=1024,
        storage_key=_STORAGE_KEY,
        created_at=_NOW,
        updated_at=_NOW,
        status=status,
        page_count=3,
    )


def _make_extractor(pages: list[tuple[int, str]]):
    return lambda _data: pages


def _make_use_case(
    *,
    chunk_repo: AsyncMock | None = None,
    storage: AsyncMock | None = None,
    embedder: AsyncMock | None = None,
    extractor=None,
    chunk_chars: int = 500,
    chunk_overlap_chars: int = 50,
) -> IngestDocumentUseCase:
    if chunk_repo is None:
        chunk_repo = AsyncMock()
        chunk_repo.save_batch = AsyncMock()
        chunk_repo.set_embeddings = AsyncMock()
    if storage is None:
        storage = AsyncMock()
        storage.get = AsyncMock(return_value=b"%PDF fake bytes")
    if embedder is None:
        embedder = AsyncMock()
        embedder.embed_documents = AsyncMock(return_value=[[0.1] * 384])
        embedder.dimension = 384
    if extractor is None:
        extractor = _make_extractor([(1, "Sample page text.")])
    return IngestDocumentUseCase(
        chunk_repo=chunk_repo,
        storage=storage,
        embedder=embedder,
        pdf_page_extractor=extractor,
        embedding_model_id="test-model",
        index_version=1,
        chunk_chars=chunk_chars,
        chunk_overlap_chars=chunk_overlap_chars,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_returns_completed_document(self) -> None:
        use_case = _make_use_case()
        doc = _make_doc()
        result = await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=doc))
        assert result.status == DocumentStatus.COMPLETED

    async def test_result_preserves_page_count_from_document(self) -> None:
        use_case = _make_use_case()
        doc = _make_doc()
        result = await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=doc))
        assert result.page_count == 3  # from doc.page_count

    async def test_storage_get_called_with_storage_key(self) -> None:
        storage = AsyncMock()
        storage.get = AsyncMock(return_value=b"%PDF fake bytes")
        use_case = _make_use_case(storage=storage)
        doc = _make_doc()
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=doc))
        storage.get.assert_called_once_with(_STORAGE_KEY)

    async def test_chunk_repo_save_batch_called(self) -> None:
        chunk_repo = AsyncMock()
        chunk_repo.save_batch = AsyncMock()
        chunk_repo.set_embeddings = AsyncMock()
        embedder = AsyncMock()
        embedder.embed_documents = AsyncMock(return_value=[[0.1] * 384])
        embedder.dimension = 384
        use_case = _make_use_case(chunk_repo=chunk_repo, embedder=embedder)
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        chunk_repo.save_batch.assert_called_once()

    async def test_embedder_called_with_chunk_texts(self) -> None:
        embedder = AsyncMock()
        embedder.embed_documents = AsyncMock(return_value=[[0.1] * 384])
        embedder.dimension = 384
        extractor = _make_extractor([(1, "hello world")])
        use_case = _make_use_case(embedder=embedder, extractor=extractor)
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        embedder.embed_documents.assert_called_once()
        texts = embedder.embed_documents.call_args.args[0]
        assert len(texts) == 1
        assert "hello world" in texts[0]

    async def test_set_embeddings_called_with_model_metadata(self) -> None:
        chunk_repo = AsyncMock()
        chunk_repo.save_batch = AsyncMock()
        chunk_repo.set_embeddings = AsyncMock()
        embedder = AsyncMock()
        embedder.embed_documents = AsyncMock(return_value=[[0.1] * 384])
        embedder.dimension = 384
        use_case = _make_use_case(chunk_repo=chunk_repo, embedder=embedder)
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        chunk_repo.set_embeddings.assert_called_once()
        kw = chunk_repo.set_embeddings.call_args.kwargs
        assert kw["model_id"] == "test-model"
        assert kw["dimension"] == 384
        assert kw["version"] == 1

    async def test_multi_page_document_produces_one_chunk_per_page(self) -> None:
        extractor = _make_extractor([(1, "Page one text."), (2, "Page two text.")])
        embedder = AsyncMock()
        embedder.embed_documents = AsyncMock(return_value=[[0.1] * 384, [0.2] * 384])
        embedder.dimension = 384
        chunk_repo = AsyncMock()
        chunk_repo.save_batch = AsyncMock()
        chunk_repo.set_embeddings = AsyncMock()
        use_case = _make_use_case(
            extractor=extractor, embedder=embedder, chunk_repo=chunk_repo
        )
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        saved_chunks = chunk_repo.save_batch.call_args.args[1]
        assert len(saved_chunks) == 2


# ---------------------------------------------------------------------------
# Empty document (no extractable text)
# ---------------------------------------------------------------------------


class TestEmptyDocument:
    async def test_empty_pdf_returns_completed_document(self) -> None:
        use_case = _make_use_case(extractor=_make_extractor([]))
        result = await use_case.execute(
            IngestDocumentCommand(scope=_SCOPE, document=_make_doc())
        )
        assert result.status == DocumentStatus.COMPLETED

    async def test_empty_pdf_does_not_call_embedder(self) -> None:
        embedder = AsyncMock()
        embedder.embed_documents = AsyncMock(return_value=[])
        embedder.dimension = 384
        use_case = _make_use_case(
            extractor=_make_extractor([]), embedder=embedder
        )
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        embedder.embed_documents.assert_not_called()

    async def test_empty_pdf_does_not_call_save_batch(self) -> None:
        chunk_repo = AsyncMock()
        chunk_repo.save_batch = AsyncMock()
        chunk_repo.set_embeddings = AsyncMock()
        use_case = _make_use_case(
            extractor=_make_extractor([]), chunk_repo=chunk_repo
        )
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        chunk_repo.save_batch.assert_not_called()


# ---------------------------------------------------------------------------
# Chunking helpers
# ---------------------------------------------------------------------------


class TestSplitText:
    def test_short_text_returns_single_segment(self) -> None:
        result = _split_text("hello world", chunk_chars=100, overlap_chars=20)
        assert result == ["hello world"]

    def test_long_text_is_split(self) -> None:
        text = "a" * 200
        result = _split_text(text, chunk_chars=100, overlap_chars=10)
        assert len(result) == 2
        assert len(result[0]) == 100
        assert len(result[1]) == 110  # 200 - 100 + 10

    def test_overlap_is_included_in_next_segment(self) -> None:
        text = "abcde" * 40  # 200 chars
        result = _split_text(text, chunk_chars=100, overlap_chars=20)
        assert result[0][-20:] == result[1][:20]

    def test_exact_length_text_returns_single_segment(self) -> None:
        result = _split_text("x" * 100, chunk_chars=100, overlap_chars=10)
        assert result == ["x" * 100]
