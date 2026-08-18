"""Unit tests for IngestDocumentUseCase.

All I/O — storage, embedder, both repositories — is mocked, and the parser is a stub
returning prepared pages and elements, so nothing here depends on a real PDF. The parser
itself is covered against actual files in the infrastructure tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from app.application.commands.ingest_document import (
    IngestDocumentCommand,
    IngestDocumentUseCase,
)
from app.domain.documents.chunker import Chunker
from app.domain.documents.entities import Document, DocumentElement, DocumentPage
from app.domain.enums import DocumentStatus, ElementType, PageKind, ProcessingMethod
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText

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


def _page(number: int, *, kind: PageKind = PageKind.NATIVE_TEXT) -> DocumentPage:
    return DocumentPage(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=_DOC_ID,
        page_number=number,
        kind=kind,
        width=612.0,
        height=792.0,
    )


def _element(page_number: int, text: str, order: int) -> DocumentElement:
    return DocumentElement(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=_DOC_ID,
        page_number=page_number,
        element_type=ElementType.PARAGRAPH,
        text=UntrustedText(text),
        reading_order=order,
        processing_method=ProcessingMethod.NATIVE_TEXT,
        created_at=_NOW,
    )


def _make_parser(
    pages: list[tuple[int, list[str]]],
    *,
    kind: PageKind = PageKind.NATIVE_TEXT,
) -> AsyncMock:
    """A parser returning prepared pages, each with its paragraph texts."""
    parsed = [
        (
            _page(number, kind=kind),
            [_element(number, text, order) for order, text in enumerate(texts)],
        )
        for number, texts in pages
    ]
    parser = AsyncMock()
    parser.parse = AsyncMock(return_value=parsed)
    return parser


class _FakeTokenCounter:
    """Counts words. Nothing here is about tokenisation — the real counter is covered
    against the model's own vocabulary in the infrastructure tests — and a fake keeps
    these from needing a downloaded vocabulary to run."""

    max_input_tokens = 512

    def count(self, text: str) -> int:
        return len(text.split())

    def fits(self, text: str) -> bool:
        return self.count(text) <= self.max_input_tokens


def _make_embedder() -> AsyncMock:
    """Returns one vector per text it is given.

    Chunk counts are a property of the chunker, not of these tests. An embedder with a
    fixed-length reply forces every caller to predict how many chunks it will produce,
    which makes an unrelated chunking change look like a failure here.
    """
    embedder = AsyncMock()
    embedder.embed_documents = AsyncMock(
        side_effect=lambda texts: [[0.1] * 384 for _ in texts]
    )
    embedder.dimension = 384
    return embedder


def _make_document_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.save_pages = AsyncMock()
    repo.save_elements = AsyncMock()
    return repo


def _make_use_case(
    *,
    chunk_repo: AsyncMock | None = None,
    document_repo: AsyncMock | None = None,
    storage: AsyncMock | None = None,
    embedder: AsyncMock | None = None,
    parser: AsyncMock | None = None,
    target_tokens: int = 500,
    max_tokens: int = 900,
) -> IngestDocumentUseCase:
    if chunk_repo is None:
        chunk_repo = AsyncMock()
        chunk_repo.save_batch = AsyncMock()
        chunk_repo.set_embeddings = AsyncMock()
    if storage is None:
        storage = AsyncMock()
        storage.get = AsyncMock(return_value=b"%PDF fake bytes")
    if embedder is None:
        embedder = _make_embedder()
    if parser is None:
        parser = _make_parser([(1, ["Sample page text."])])
    return IngestDocumentUseCase(
        chunk_repo=chunk_repo,
        document_repo=document_repo or _make_document_repo(),
        storage=storage,
        embedder=embedder,
        parser=parser,
        chunker=Chunker(
            _FakeTokenCounter().count,
            target_tokens=target_tokens,
            max_tokens=max_tokens,
            overlap_tokens=0,
        ),
        embedding_model_id="test-model",
        index_version=1,
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

    async def test_page_count_comes_from_the_parse(self) -> None:
        """The parse counted the pages, so it is the authority — not the count the
        document was carrying from upload-time validation."""
        embedder = _make_embedder()
        use_case = _make_use_case(
            parser=_make_parser([(1, ["a"]), (2, ["b"])]), embedder=embedder
        )
        doc = _make_doc()  # carries page_count=3
        result = await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=doc))
        assert result.page_count == 2

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
        parser = _make_parser([(1, ["hello world"])])
        use_case = _make_use_case(embedder=embedder, parser=parser)
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

    async def test_chunks_follow_sections_rather_than_pages(self) -> None:
        """A section that continues onto the next page is one passage, not two. The old
        splitter chunked per page and cut every section at the page break."""
        parser = _make_parser([(1, ["Page one text."]), (2, ["Page two text."])])
        chunk_repo = AsyncMock()
        chunk_repo.save_batch = AsyncMock()
        chunk_repo.set_embeddings = AsyncMock()
        use_case = _make_use_case(parser=parser, chunk_repo=chunk_repo)
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        saved_chunks = chunk_repo.save_batch.call_args.args[1]
        assert len(saved_chunks) == 1
        assert saved_chunks[0].page_start == 1
        assert saved_chunks[0].page_end == 2


# ---------------------------------------------------------------------------
# A document whose pages yield no text
# ---------------------------------------------------------------------------


def _scanned_parser(page_count: int = 2) -> AsyncMock:
    """Pages that exist and produced nothing — what a scanned document looks like
    before recognition has run over it."""
    return _make_parser(
        [(number, []) for number in range(1, page_count + 1)], kind=PageKind.SCANNED
    )


class TestDocumentWithNoExtractableText:
    async def test_it_still_completes(self) -> None:
        use_case = _make_use_case(parser=_scanned_parser())
        result = await use_case.execute(
            IngestDocumentCommand(scope=_SCOPE, document=_make_doc())
        )
        assert result.status == DocumentStatus.COMPLETED

    async def test_its_pages_are_still_recorded(self) -> None:
        """The pages exist and are known to need recognition. Losing that because no
        text came out would leave nothing for a later stage to work from."""
        document_repo = _make_document_repo()
        use_case = _make_use_case(parser=_scanned_parser(), document_repo=document_repo)
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        saved = document_repo.save_pages.call_args.args[1]
        assert [page.page_number for page in saved] == [1, 2]
        assert all(page.kind is PageKind.SCANNED for page in saved)

    async def test_page_count_still_reflects_the_parse(self) -> None:
        use_case = _make_use_case(parser=_scanned_parser(page_count=5))
        result = await use_case.execute(
            IngestDocumentCommand(scope=_SCOPE, document=_make_doc())
        )
        assert result.page_count == 5

    async def test_no_elements_are_written(self) -> None:
        document_repo = _make_document_repo()
        use_case = _make_use_case(parser=_scanned_parser(), document_repo=document_repo)
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        document_repo.save_elements.assert_not_called()

    async def test_the_embedder_is_not_called(self) -> None:
        embedder = AsyncMock()
        embedder.embed_documents = AsyncMock(return_value=[])
        embedder.dimension = 384
        use_case = _make_use_case(parser=_scanned_parser(), embedder=embedder)
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        embedder.embed_documents.assert_not_called()

    async def test_no_chunks_are_written(self) -> None:
        chunk_repo = AsyncMock()
        chunk_repo.save_batch = AsyncMock()
        chunk_repo.set_embeddings = AsyncMock()
        use_case = _make_use_case(parser=_scanned_parser(), chunk_repo=chunk_repo)
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        chunk_repo.save_batch.assert_not_called()


# ---------------------------------------------------------------------------
# Pages and elements
# ---------------------------------------------------------------------------


class TestPageAndElementPersistence:
    async def test_pages_are_saved_under_the_calling_scope(self) -> None:
        document_repo = _make_document_repo()
        use_case = _make_use_case(document_repo=document_repo)
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        assert document_repo.save_pages.call_args.args[0] == _SCOPE

    async def test_elements_are_saved_under_the_calling_scope(self) -> None:
        document_repo = _make_document_repo()
        use_case = _make_use_case(document_repo=document_repo)
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        assert document_repo.save_elements.call_args.args[0] == _SCOPE

    async def test_elements_from_every_page_are_saved_together(self) -> None:
        document_repo = _make_document_repo()
        parser = _make_parser([(1, ["one", "two"]), (2, ["three"])])
        embedder = _make_embedder()
        use_case = _make_use_case(
            parser=parser, document_repo=document_repo, embedder=embedder
        )
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        saved = document_repo.save_elements.call_args.args[1]
        assert [element.text.value for element in saved] == ["one", "two", "three"]

    async def test_pages_are_saved_before_chunks(self) -> None:
        """A parse that established pages should not lose them because a later stage
        failed."""
        order: list[str] = []
        document_repo = _make_document_repo()
        document_repo.save_pages = AsyncMock(
            side_effect=lambda *_a, **_k: order.append("pages")
        )
        chunk_repo = AsyncMock()
        chunk_repo.save_batch = AsyncMock(
            side_effect=lambda *_a, **_k: order.append("chunks")
        )
        chunk_repo.set_embeddings = AsyncMock()
        use_case = _make_use_case(document_repo=document_repo, chunk_repo=chunk_repo)
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        assert order == ["pages", "chunks"]

    async def test_the_parser_is_given_the_document_id_and_scope(self) -> None:
        parser = _make_parser([(1, ["text"])])
        use_case = _make_use_case(parser=parser)
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        kwargs = parser.parse.call_args.kwargs
        assert kwargs["document_id"] == _DOC_ID
        assert kwargs["scope"] == _SCOPE

    async def test_paragraphs_reach_the_chunker_separated(self) -> None:
        """Paragraph boundaries survive into the text the splitter sees, ready for the
        splitter that will eventually respect them."""
        chunk_repo = AsyncMock()
        chunk_repo.save_batch = AsyncMock()
        chunk_repo.set_embeddings = AsyncMock()
        use_case = _make_use_case(
            parser=_make_parser([(1, ["first para", "second para"])]),
            chunk_repo=chunk_repo,
        )
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        text = chunk_repo.save_batch.call_args.args[1][0].text.value
        assert text == "first para\n\nsecond para"
