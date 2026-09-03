"""Unit tests for IngestDocumentUseCase.

All I/O — storage, embedder, both repositories — is mocked, and the parser is a stub
returning prepared pages and elements, so nothing here depends on a real PDF. The parser
itself is covered against actual files in the infrastructure tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.application.commands.ingest_document import (
    IngestDocumentCommand,
    IngestDocumentResult,
    IngestDocumentUseCase,
)
from app.domain.documents.chunker import Chunker
from app.domain.documents.entities import (
    Document,
    DocumentElement,
    DocumentPage,
    ParsedPage,
)
from app.domain.documents.figures import DocumentFigure
from app.domain.documents.tables import DocumentTable
from app.domain.enums import (
    ChunkType,
    DocumentStatus,
    ElementType,
    PageKind,
    ProcessingMethod,
)
from app.domain.scope import ScopeContext
from app.domain.values import BoundingBox, UntrustedText

_NOW = datetime(2025, 1, 15, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_DOC_ID = uuid.uuid4()
_STORAGE_KEY = f"{_USER_ID}/{_KB_ID}/{_DOC_ID}/original.pdf"

_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)

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
        ParsedPage(
            page=_page(number, kind=kind),
            elements=[_element(number, text, order) for order, text in enumerate(texts)],
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


def _make_document_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.save_pages = AsyncMock()
    repo.save_elements = AsyncMock()
    # An empty list, not a mock: this is read to find the crops an earlier ingestion
    # left in storage, and the default document under test has never been read before.
    repo.get_figures = AsyncMock(return_value=[])
    return repo


def _make_use_case(
    *,
    chunk_repo: AsyncMock | None = None,
    document_repo: AsyncMock | None = None,
    storage: AsyncMock | None = None,
    parser: AsyncMock | None = None,
    figure_cropper: AsyncMock | None = None,
    model_gateway: AsyncMock | None = None,
    target_tokens: int = 500,
    max_tokens: int = 900,
    parent_target_tokens: int = 1200,
    parent_max_tokens: int = 1500,
) -> IngestDocumentUseCase:
    if chunk_repo is None:
        chunk_repo = AsyncMock()
        chunk_repo.save_batch = AsyncMock()
    if storage is None:
        storage = AsyncMock()
        storage.get = AsyncMock(return_value=b"%PDF fake bytes")
        storage.put = AsyncMock()
    if parser is None:
        parser = _make_parser([(1, ["Sample page text."])])
    return IngestDocumentUseCase(
        chunk_repo=chunk_repo,
        document_repo=document_repo or _make_document_repo(),
        storage=storage,
        parser=parser,
        chunker=Chunker(
            _FakeTokenCounter().count,
            target_tokens=target_tokens,
            max_tokens=max_tokens,
            overlap_tokens=0,
            parent_target_tokens=parent_target_tokens,
            parent_max_tokens=parent_max_tokens,
        ),
        index_version=1,
        figure_cropper=figure_cropper,
        crops_prefix="figures",
        model_gateway=model_gateway,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_returns_completed_document(self) -> None:
        use_case = _make_use_case()
        doc = _make_doc()
        result = await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=doc))
        assert result.document.status == DocumentStatus.COMPLETED

    async def test_page_count_comes_from_the_parse(self) -> None:
        """The parse counted the pages, so it is the authority — not the count the
        document was carrying from upload-time validation."""
        use_case = _make_use_case(parser=_make_parser([(1, ["a"]), (2, ["b"])]))
        doc = _make_doc()  # carries page_count=3
        result = await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=doc))
        assert result.document.page_count == 2

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
        use_case = _make_use_case(chunk_repo=chunk_repo)
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        chunk_repo.save_batch.assert_called_once()

    async def test_searchable_chunk_ids_populated_for_child_chunks(self) -> None:
        parser = _make_parser([(1, ["hello world"])])
        result = await _make_use_case(parser=parser).execute(
            IngestDocumentCommand(scope=_SCOPE, document=_make_doc())
        )
        assert len(result.searchable_chunk_ids) >= 1

    async def test_searchable_chunk_ids_contains_only_child_ids(self) -> None:
        chunk_repo = AsyncMock()
        chunk_repo.save_batch = AsyncMock()
        result = await _make_use_case(chunk_repo=chunk_repo).execute(
            IngestDocumentCommand(scope=_SCOPE, document=_make_doc())
        )
        saved_children = {
            c.id for c in chunk_repo.save_batch.call_args.args[1] if c.is_child
        }
        assert set(result.searchable_chunk_ids) == saved_children

    async def test_chunks_follow_sections_rather_than_pages(self) -> None:
        """A section that continues onto the next page is one passage, not two. The old
        splitter chunked per page and cut every section at the page break."""
        parser = _make_parser([(1, ["Page one text."]), (2, ["Page two text."])])
        chunk_repo = AsyncMock()
        chunk_repo.save_batch = AsyncMock()
        use_case = _make_use_case(parser=parser, chunk_repo=chunk_repo)
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        children = [c for c in chunk_repo.save_batch.call_args.args[1] if c.is_child]
        assert len(children) == 1
        assert children[0].page_start == 1
        assert children[0].page_end == 2


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
        assert result.document.status == DocumentStatus.COMPLETED

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
        assert result.document.page_count == 5

    async def test_no_elements_are_written(self) -> None:
        document_repo = _make_document_repo()
        use_case = _make_use_case(parser=_scanned_parser(), document_repo=document_repo)
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        document_repo.save_elements.assert_not_called()

    async def test_no_searchable_chunk_ids_for_scanned_document(self) -> None:
        result = await _make_use_case(parser=_scanned_parser()).execute(
            IngestDocumentCommand(scope=_SCOPE, document=_make_doc())
        )
        assert result.searchable_chunk_ids == ()

    async def test_no_chunks_are_written(self) -> None:
        chunk_repo = AsyncMock()
        chunk_repo.save_batch = AsyncMock()
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
        use_case = _make_use_case(parser=parser, document_repo=document_repo)
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
        use_case = _make_use_case(
            parser=_make_parser([(1, ["first para", "second para"])]),
            chunk_repo=chunk_repo,
        )
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))
        text = chunk_repo.save_batch.call_args.args[1][0].text.value
        assert text == "first para\n\nsecond para"


# ---------------------------------------------------------------------------
# The two tiers
# ---------------------------------------------------------------------------


def _split_use_case(chunk_repo: AsyncMock) -> IngestDocumentUseCase:
    """Sizes small enough that the prepared pages produce several children per parent."""
    return _make_use_case(
        chunk_repo=chunk_repo,
        parser=_make_parser(
            [(1, [f"paragraph number {i}" for i in range(4)]), (2, ["a closing remark"])]
        ),
        target_tokens=3,
        max_tokens=8,
        parent_target_tokens=9,
        parent_max_tokens=20,
    )


def _chunk_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.save_batch = AsyncMock()
    return repo


class TestParentAndChildChunks:
    async def test_both_tiers_are_written(self) -> None:
        repo = _chunk_repo()
        await _split_use_case(repo).execute(
            IngestDocumentCommand(scope=_SCOPE, document=_make_doc())
        )
        saved = repo.save_batch.call_args.args[1]
        assert any(c.is_parent for c in saved)
        assert any(c.is_child for c in saved)

    async def test_every_child_names_a_parent(self) -> None:
        """Expansion has to have something to follow, and a child with no parent would
        be retrieved and then presented with no more context than it already had."""
        repo = _chunk_repo()
        await _split_use_case(repo).execute(
            IngestDocumentCommand(scope=_SCOPE, document=_make_doc())
        )
        saved = repo.save_batch.call_args.args[1]
        parent_ids = {c.id for c in saved if c.is_parent}
        children = [c for c in saved if c.is_child]

        assert children
        for child in children:
            assert child.parent_chunk_id in parent_ids

    async def test_a_parent_is_written_before_the_children_naming_it(self) -> None:
        """The column is a foreign key onto the same table, so a child inserted first
        would point at a row that does not exist yet."""
        repo = _chunk_repo()
        await _split_use_case(repo).execute(
            IngestDocumentCommand(scope=_SCOPE, document=_make_doc())
        )
        saved = repo.save_batch.call_args.args[1]
        seen: set[uuid.UUID] = set()
        for chunk in saved:
            if chunk.parent_chunk_id is not None:
                assert chunk.parent_chunk_id in seen
            seen.add(chunk.id)

    async def test_a_parent_holds_the_text_of_its_children(self) -> None:
        repo = _chunk_repo()
        await _split_use_case(repo).execute(
            IngestDocumentCommand(scope=_SCOPE, document=_make_doc())
        )
        saved = repo.save_batch.call_args.args[1]
        parents = {c.id: c for c in saved if c.is_parent}

        for child in (c for c in saved if c.is_child):
            parent = parents[child.parent_chunk_id]
            assert " ".join(child.text.value.split()) in " ".join(parent.text.value.split())

    async def test_the_tiers_are_numbered_separately(self) -> None:
        """An ordinal places a chunk among the chunks like it. One sequence across both
        would make the neighbours of a passage depend on how the tier above was cut."""
        repo = _chunk_repo()
        await _split_use_case(repo).execute(
            IngestDocumentCommand(scope=_SCOPE, document=_make_doc())
        )
        saved = repo.save_batch.call_args.args[1]

        assert [c.ordinal for c in saved if c.is_parent] == list(
            range(len([c for c in saved if c.is_parent]))
        )
        assert [c.ordinal for c in saved if c.is_child] == list(
            range(len([c for c in saved if c.is_child]))
        )

    async def test_only_children_are_in_searchable_chunk_ids(self) -> None:
        """A parent is what a hit expands into, not something to match: only child IDs
        are returned for embedding."""
        repo = _chunk_repo()
        use_case = _make_use_case(
            chunk_repo=repo,
            parser=_make_parser(
                [(1, [f"paragraph number {i}" for i in range(4)]), (2, ["a closing remark"])]
            ),
            target_tokens=3,
            max_tokens=8,
            parent_target_tokens=9,
            parent_max_tokens=20,
        )
        result = await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        saved = repo.save_batch.call_args.args[1]
        child_ids = {c.id for c in saved if c.is_child}

        assert set(result.searchable_chunk_ids) == child_ids

    async def test_a_parent_carries_the_documents_scope(self) -> None:
        repo = _chunk_repo()
        await _split_use_case(repo).execute(
            IngestDocumentCommand(scope=_SCOPE, document=_make_doc())
        )
        for chunk in repo.save_batch.call_args.args[1]:
            assert chunk.scope == _SCOPE
            assert chunk.document_id == _DOC_ID


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


_TABLE_BOX = BoundingBox(x0=10.0, y0=20.0, x1=200.0, y1=120.0)


def _make_chunk_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.save_batch = AsyncMock()
    return repo


def _parser_with_a_table() -> tuple[AsyncMock, DocumentElement]:
    """A parser returning one page holding a table, with its joined element beside it."""
    element = DocumentElement(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=_DOC_ID,
        page_number=1,
        element_type=ElementType.TABLE,
        text=UntrustedText("Metal | Density\nAluminium | 2.70"),
        reading_order=0,
        processing_method=ProcessingMethod.NATIVE_TEXT,
        created_at=_NOW,
        bounding_box=_TABLE_BOX,
    )
    table = DocumentTable(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=_DOC_ID,
        source_element_id=element.id,
        page_number=1,
        headers=("Metal", "Density"),
        rows=(("Aluminium", "2.70"),),
        units=(None, "g/cm3"),
        bounding_box=_TABLE_BOX,
        created_at=_NOW,
    )
    parser = AsyncMock()
    parser.parse = AsyncMock(
        return_value=[ParsedPage(page=_page(1), elements=[element], tables=[table])]
    )
    return parser, element


class TestTablePersistence:
    async def test_tables_are_saved_under_the_calling_scope(self) -> None:
        parser, _ = _parser_with_a_table()
        document_repo = _make_document_repo()
        use_case = _make_use_case(parser=parser, document_repo=document_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        document_repo.save_tables.assert_awaited_once()
        assert document_repo.save_tables.await_args.args[0] == _SCOPE

    async def test_tables_are_saved_after_the_elements_they_name(self) -> None:
        # A table refers to its element, so that row has to exist first.
        parser, _ = _parser_with_a_table()
        document_repo = _make_document_repo()
        order: list[str] = []
        document_repo.save_elements.side_effect = lambda *a, **k: order.append("elements")
        document_repo.save_tables.side_effect = lambda *a, **k: order.append("tables")
        use_case = _make_use_case(parser=parser, document_repo=document_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        assert order == ["elements", "tables"]

    async def test_a_saved_table_carries_every_rendered_form(self) -> None:
        parser, _ = _parser_with_a_table()
        document_repo = _make_document_repo()
        use_case = _make_use_case(parser=parser, document_repo=document_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        saved = document_repo.save_tables.await_args.args[1][0]
        assert saved.is_rendered
        assert saved.markdown
        assert saved.html
        assert saved.table_json

    async def test_the_stored_element_keeps_the_literal_reading(self) -> None:
        # The element records what the region says; only the copy handed to the chunker
        # carries the rendered prose.
        parser, element = _parser_with_a_table()
        document_repo = _make_document_repo()
        use_case = _make_use_case(parser=parser, document_repo=document_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        saved = document_repo.save_elements.await_args.args[1][0]
        assert saved.text.value == element.text.value

    async def test_the_table_chunk_holds_the_rendered_prose(self) -> None:
        parser, _ = _parser_with_a_table()
        chunk_repo = _make_chunk_repo()
        use_case = _make_use_case(parser=parser, chunk_repo=chunk_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        written = chunk_repo.save_batch.await_args.args[1]
        table_chunks = [c for c in written if c.chunk_type is ChunkType.TABLE]
        assert table_chunks
        # Column names paired with values, rather than the joined cells.
        assert "Metal Aluminium" in table_chunks[0].text.value

    async def test_the_units_reach_the_embedded_text(self) -> None:
        parser, _ = _parser_with_a_table()
        chunk_repo = _make_chunk_repo()
        use_case = _make_use_case(parser=parser, chunk_repo=chunk_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        written = chunk_repo.save_batch.await_args.args[1]
        table_chunks = [c for c in written if c.chunk_type is ChunkType.TABLE]
        assert "g/cm3" in table_chunks[0].text.value

    async def test_a_document_with_no_tables_writes_none(self) -> None:
        document_repo = _make_document_repo()
        use_case = _make_use_case(
            parser=_make_parser([(1, ["A paragraph of prose."])]),
            document_repo=document_repo,
        )

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        document_repo.save_tables.assert_not_awaited()


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


_FIGURE_BOX = BoundingBox(x0=50.0, y0=200.0, x1=400.0, y1=500.0)


def _parser_with_a_figure() -> AsyncMock:
    """A parser returning one page holding a figure element and its visual record."""

    element = DocumentElement(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=_DOC_ID,
        page_number=1,
        element_type=ElementType.FIGURE,
        text=UntrustedText(""),
        reading_order=0,
        processing_method=ProcessingMethod.NATIVE_TEXT,
        created_at=_NOW,
        bounding_box=_FIGURE_BOX,
    )
    figure = DocumentFigure(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=_DOC_ID,
        source_element_id=element.id,
        page_number=1,
        kind=ElementType.FIGURE,
        bounding_box=_FIGURE_BOX,
        created_at=_NOW,
    )
    parser = AsyncMock()
    parser.parse = AsyncMock(
        return_value=[ParsedPage(page=_page(1), elements=[element], figures=[figure])]
    )
    return parser


class TestFigurePersistence:
    async def test_figures_are_saved_under_the_calling_scope(self) -> None:
        document_repo = _make_document_repo()
        use_case = _make_use_case(parser=_parser_with_a_figure(), document_repo=document_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        document_repo.save_figures.assert_awaited_once()
        assert document_repo.save_figures.await_args.args[0] == _SCOPE

    async def test_figures_are_saved_after_the_elements_they_name(self) -> None:
        document_repo = _make_document_repo()
        order: list[str] = []
        document_repo.save_elements.side_effect = lambda *a, **k: order.append("elements")
        document_repo.save_figures.side_effect = lambda *a, **k: order.append("figures")
        use_case = _make_use_case(parser=_parser_with_a_figure(), document_repo=document_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        assert order.index("elements") < order.index("figures")

    async def test_a_document_with_no_figures_writes_none(self) -> None:
        document_repo = _make_document_repo()
        use_case = _make_use_case(
            parser=_make_parser([(1, ["A paragraph of prose."])]),
            document_repo=document_repo,
        )

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        document_repo.save_figures.assert_not_awaited()


# ---------------------------------------------------------------------------
# Figure cropping
# ---------------------------------------------------------------------------


def _make_cropper(crop_bytes: bytes = b"\x89PNG fake crop") -> AsyncMock:
    cropper = AsyncMock()
    cropper.crop = AsyncMock(return_value=crop_bytes)
    return cropper


class TestFigureCropping:
    async def test_crop_is_uploaded_to_storage(self) -> None:
        storage = AsyncMock()
        storage.get = AsyncMock(return_value=b"%PDF fake bytes")
        storage.put = AsyncMock()
        cropper = _make_cropper()

        use_case = _make_use_case(
            parser=_parser_with_a_figure(),
            storage=storage,
            figure_cropper=cropper,
        )
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        storage.put.assert_awaited_once()
        key, crop_bytes = (
            storage.put.await_args.args[0],
            storage.put.await_args.args[1],
        )
        assert crop_bytes == b"\x89PNG fake crop"
        assert key.startswith("figures/")
        assert "png" in key

    async def test_saved_figure_carries_the_crop_key(self) -> None:
        document_repo = _make_document_repo()
        storage = AsyncMock()
        storage.get = AsyncMock(return_value=b"%PDF fake bytes")
        storage.put = AsyncMock()

        use_case = _make_use_case(
            parser=_parser_with_a_figure(),
            document_repo=document_repo,
            storage=storage,
            figure_cropper=_make_cropper(),
        )
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        saved = document_repo.save_figures.await_args.args[1][0]
        assert saved.crop_key is not None
        assert saved.crop_key.startswith("figures/")

    async def test_crop_key_scoped_to_user_kb_and_document(self) -> None:
        document_repo = _make_document_repo()
        storage = AsyncMock()
        storage.get = AsyncMock(return_value=b"%PDF fake bytes")
        storage.put = AsyncMock()

        use_case = _make_use_case(
            parser=_parser_with_a_figure(),
            document_repo=document_repo,
            storage=storage,
            figure_cropper=_make_cropper(),
        )
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        saved = document_repo.save_figures.await_args.args[1][0]
        assert str(_USER_ID) in saved.crop_key
        assert str(_KB_ID) in saved.crop_key
        assert str(_DOC_ID) in saved.crop_key

    async def test_no_cropper_leaves_crop_key_null(self) -> None:
        document_repo = _make_document_repo()

        use_case = _make_use_case(
            parser=_parser_with_a_figure(),
            document_repo=document_repo,
            figure_cropper=None,
        )
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        saved = document_repo.save_figures.await_args.args[1][0]
        assert saved.crop_key is None

    async def test_crop_failure_leaves_figure_with_null_crop_key(self) -> None:
        document_repo = _make_document_repo()
        storage = AsyncMock()
        storage.get = AsyncMock(return_value=b"%PDF fake bytes")
        storage.put = AsyncMock()

        cropper = AsyncMock()
        cropper.crop = AsyncMock(side_effect=ValueError("render failed"))

        use_case = _make_use_case(
            parser=_parser_with_a_figure(),
            document_repo=document_repo,
            storage=storage,
            figure_cropper=cropper,
        )
        # Should not raise — crop failure is logged and skipped
        result = await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        assert result.document.status.name == "COMPLETED"
        saved = document_repo.save_figures.await_args.args[1][0]
        assert saved.crop_key is None
        storage.put.assert_not_awaited()


# ---------------------------------------------------------------------------
# Figure description (step 6.7)
# ---------------------------------------------------------------------------

_FIGURE_JSON = '{"kind":"FIGURE","description":"A photograph of a cell.","ocr_text":null}'
_CHART_JSON = (
    '{"kind":"CHART","description":"Line chart of accuracy over epochs.",'
    '"ocr_text":"Accuracy","chart_type":"line","x_axis_label":"Epoch",'
    '"y_axis_label":"Accuracy","units_label":null,"legend":"Train,Val",'
    '"data_labels":null,"visible_trend":"Accuracy rises then plateaus.",'
    '"diagram_labels":[],"components":[],"arrows":[],"visible_relationships":[]}'
)
_DIAGRAM_JSON = (
    '{"kind":"DIAGRAM","description":"Data flow between components.",'
    '"ocr_text":"Input Output","chart_type":null,"x_axis_label":null,'
    '"y_axis_label":null,"units_label":null,"legend":null,"data_labels":null,'
    '"visible_trend":null,"diagram_labels":["Input","Output"],'
    '"components":["Parser","Embedder"],"arrows":["Parser -> Embedder"],'
    '"visible_relationships":["Parser feeds Embedder"]}'
)


def _make_vision_gateway(response_json: str = _FIGURE_JSON) -> AsyncMock:
    from app.domain.enums import ModelTask
    from app.domain.models.entities import ModelResponse
    from app.domain.values import UntrustedText

    mock_response = ModelResponse(
        model_task=ModelTask.VISUAL_QUESTION,
        model_id="gemma3:4b",
        content=UntrustedText(response_json),
        prompt_tokens=50,
        completion_tokens=80,
        finish_reason="stop",
        latency_ms=200,
    )
    gateway = AsyncMock()
    gateway.generate_with_image = AsyncMock(return_value=mock_response)
    return gateway


def _parser_with_cropped_figure() -> AsyncMock:
    """Parser returning a figure that already has a crop_key set."""

    element = DocumentElement(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=_DOC_ID,
        page_number=1,
        element_type=ElementType.FIGURE,
        text=UntrustedText(""),
        reading_order=0,
        processing_method=ProcessingMethod.NATIVE_TEXT,
        created_at=_NOW,
        bounding_box=_FIGURE_BOX,
    )
    figure = DocumentFigure(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=_DOC_ID,
        source_element_id=element.id,
        page_number=1,
        kind=ElementType.FIGURE,
        bounding_box=_FIGURE_BOX,
        created_at=_NOW,
        crop_key="figures/u/k/d/fig.png",
    )
    parser = AsyncMock()
    parser.parse = AsyncMock(
        return_value=[ParsedPage(page=_page(1), elements=[element], figures=[figure])]
    )
    return parser


class TestFigureDescription:
    async def test_description_is_set_on_figure(self) -> None:
        document_repo = _make_document_repo()
        storage = AsyncMock()
        storage.get = AsyncMock(return_value=b"%PDF fake bytes")
        storage.put = AsyncMock()

        use_case = _make_use_case(
            parser=_parser_with_cropped_figure(),
            document_repo=document_repo,
            storage=storage,
            model_gateway=_make_vision_gateway(_FIGURE_JSON),
        )
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        saved = document_repo.save_figures.await_args.args[1][0]
        assert saved.description == "A photograph of a cell."

    async def test_kind_upgraded_from_figure_to_chart(self) -> None:
        document_repo = _make_document_repo()
        storage = AsyncMock()
        storage.get = AsyncMock(return_value=b"%PDF fake bytes")
        storage.put = AsyncMock()

        use_case = _make_use_case(
            parser=_parser_with_cropped_figure(),
            document_repo=document_repo,
            storage=storage,
            model_gateway=_make_vision_gateway(_CHART_JSON),
        )
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        saved = document_repo.save_figures.await_args.args[1][0]
        assert saved.kind is ElementType.CHART
        assert saved.chart_type == "line"
        assert saved.x_axis_label == "Epoch"
        assert saved.y_axis_label == "Accuracy"
        assert saved.visible_trend == "Accuracy rises then plateaus."

    async def test_kind_upgraded_from_figure_to_diagram(self) -> None:
        document_repo = _make_document_repo()
        storage = AsyncMock()
        storage.get = AsyncMock(return_value=b"%PDF fake bytes")
        storage.put = AsyncMock()

        use_case = _make_use_case(
            parser=_parser_with_cropped_figure(),
            document_repo=document_repo,
            storage=storage,
            model_gateway=_make_vision_gateway(_DIAGRAM_JSON),
        )
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        saved = document_repo.save_figures.await_args.args[1][0]
        assert saved.kind is ElementType.DIAGRAM
        assert "Input" in saved.diagram_labels
        assert "Parser -> Embedder" in saved.arrows

    async def test_figure_without_crop_key_is_not_sent_to_model(self) -> None:
        document_repo = _make_document_repo()
        gateway = _make_vision_gateway()

        use_case = _make_use_case(
            parser=_parser_with_a_figure(),  # no crop_key on this parser's figure
            document_repo=document_repo,
            model_gateway=gateway,
        )
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        gateway.generate_with_image.assert_not_awaited()

    async def test_description_failure_leaves_figure_unchanged(self) -> None:
        document_repo = _make_document_repo()
        storage = AsyncMock()
        storage.get = AsyncMock(return_value=b"%PDF fake bytes")
        storage.put = AsyncMock()

        gateway = AsyncMock()
        gateway.generate_with_image = AsyncMock(side_effect=RuntimeError("model error"))

        use_case = _make_use_case(
            parser=_parser_with_cropped_figure(),
            document_repo=document_repo,
            storage=storage,
            model_gateway=gateway,
        )
        result = await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        assert result.document.status.name == "COMPLETED"
        saved = document_repo.save_figures.await_args.args[1][0]
        assert saved.description is None

    async def test_no_gateway_leaves_description_null(self) -> None:
        document_repo = _make_document_repo()

        use_case = _make_use_case(
            parser=_parser_with_cropped_figure(),
            document_repo=document_repo,
            model_gateway=None,
        )
        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        saved = document_repo.save_figures.await_args.args[1][0]
        assert saved.description is None


def _parser_with_a_described_figure() -> AsyncMock:
    """A figure that the vision stage has already read, as it is by the time chunking runs.

    The element text stays empty, which is what the parser produces for an image region.
    Everything a reader would call the figure's content sits on the figure record.
    """
    element = DocumentElement(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=_DOC_ID,
        page_number=1,
        element_type=ElementType.FIGURE,
        text=UntrustedText(""),
        reading_order=0,
        processing_method=ProcessingMethod.NATIVE_TEXT,
        created_at=_NOW,
        bounding_box=_FIGURE_BOX,
    )
    figure = DocumentFigure(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=_DOC_ID,
        source_element_id=element.id,
        page_number=1,
        kind=ElementType.FIGURE,
        bounding_box=_FIGURE_BOX,
        created_at=_NOW,
        number="Figure 4",
        caption=UntrustedText("Model training workflow"),
        description="A four-stage pipeline from data input through to evaluation.",
        ocr_text="Data input Transformations Model Definition Training",
    )
    parser = AsyncMock()
    parser.parse = AsyncMock(
        return_value=[ParsedPage(page=_page(1), elements=[element], figures=[figure])]
    )
    return parser


class TestFigureChunks:
    """A figure has to become a chunk, or it cannot be retrieved at all.

    The element a figure is parsed from has no text — its content lives on the figure
    record. Handing the chunker the bare element produces nothing, which leaves every
    figure in a document unreachable however well the vision stage read it.
    """

    async def test_a_described_figure_becomes_a_figure_chunk(self) -> None:
        chunk_repo = _make_chunk_repo()
        use_case = _make_use_case(parser=_parser_with_a_described_figure(), chunk_repo=chunk_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        written = chunk_repo.save_batch.await_args.args[1]
        assert [c for c in written if c.chunk_type is ChunkType.FIGURE]

    async def test_the_figure_chunk_carries_caption_description_and_ocr(self) -> None:
        chunk_repo = _make_chunk_repo()
        use_case = _make_use_case(parser=_parser_with_a_described_figure(), chunk_repo=chunk_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        written = chunk_repo.save_batch.await_args.args[1]
        text = next(c for c in written if c.chunk_type is ChunkType.FIGURE).text.value
        assert "Model training workflow" in text
        assert "four-stage pipeline" in text
        assert "Model Definition" in text

    async def test_the_stored_element_keeps_its_empty_text(self) -> None:
        """Only the copy handed to the chunker changes; the element records the region."""
        document_repo = _make_document_repo()
        use_case = _make_use_case(
            parser=_parser_with_a_described_figure(), document_repo=document_repo
        )

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        saved = document_repo.save_elements.await_args.args[1][0]
        assert saved.text.value == ""

    async def test_a_figure_nothing_is_known_about_produces_no_chunk(self) -> None:
        """An unread figure has no prose to match on, so an empty chunk would be noise."""
        chunk_repo = _make_chunk_repo()
        use_case = _make_use_case(parser=_parser_with_a_figure(), chunk_repo=chunk_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        written = (
            chunk_repo.save_batch.await_args.args[1] if chunk_repo.save_batch.await_args else []
        )
        assert not [c for c in written if c.chunk_type is ChunkType.FIGURE]


# ---------------------------------------------------------------------------
# Replacing an earlier reading
# ---------------------------------------------------------------------------


def _previous_figure(*, crop_key: str | None = "figures/u/kb/doc/fig.png") -> DocumentFigure:
    """A figure record an earlier ingestion of this same document left behind."""
    return DocumentFigure(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=_DOC_ID,
        source_element_id=uuid.uuid4(),
        page_number=1,
        kind=ElementType.FIGURE,
        bounding_box=_FIGURE_BOX,
        created_at=_NOW,
        crop_key=crop_key,
    )


def _repo_holding(figures: list[DocumentFigure]) -> AsyncMock:
    repo = _make_document_repo()
    repo.get_figures = AsyncMock(return_value=figures)
    return repo


def _storage_with_a_pdf() -> AsyncMock:
    storage = AsyncMock()
    storage.get = AsyncMock(return_value=b"%PDF fake bytes")
    return storage


class TestReplacingAnEarlierReading:
    """Reading a document twice must leave one copy of it, not two.

    Nothing written here carries an identity a previous run would recognise, so saving
    again inserts rather than overwrites. Without the sweep the same passage sits in the
    index under two ids and competes with itself for the slots an answer has to spend.
    """

    async def test_the_chunks_of_the_earlier_reading_are_removed(self) -> None:
        chunk_repo = AsyncMock()
        use_case = _make_use_case(chunk_repo=chunk_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        chunk_repo.delete_for_document.assert_awaited_once_with(_SCOPE, _DOC_ID)

    async def test_the_pages_and_elements_of_the_earlier_reading_are_removed(self) -> None:
        document_repo = _make_document_repo()
        use_case = _make_use_case(document_repo=document_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        document_repo.delete_parse.assert_awaited_once_with(_SCOPE, _DOC_ID)

    async def test_nothing_new_is_written_until_the_old_is_gone(self) -> None:
        """Overlap would put both readings in the tables at once, and a search running
        during the window would rank a passage against itself."""
        document_repo = _make_document_repo()
        chunk_repo = AsyncMock()
        order: list[str] = []
        document_repo.delete_parse.side_effect = lambda *_a, **_k: order.append("clear parse")
        chunk_repo.delete_for_document.side_effect = lambda *_a, **_k: order.append("clear chunks")
        document_repo.save_pages.side_effect = lambda *_a, **_k: order.append("write pages")
        chunk_repo.save_batch.side_effect = lambda *_a, **_k: order.append("write chunks")
        use_case = _make_use_case(document_repo=document_repo, chunk_repo=chunk_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        assert order.index("clear parse") < order.index("write pages")
        assert order.index("clear chunks") < order.index("write chunks")

    async def test_a_parse_that_fails_leaves_the_earlier_reading_untouched(self) -> None:
        """Sweeping first would mean a corrupt upload, a crashed parser or a dropped
        connection took away the copy the student already had and put nothing back."""
        document_repo = _make_document_repo()
        chunk_repo = AsyncMock()
        parser = AsyncMock()
        parser.parse = AsyncMock(side_effect=RuntimeError("this file is not a PDF"))
        use_case = _make_use_case(
            parser=parser, document_repo=document_repo, chunk_repo=chunk_repo
        )

        with pytest.raises(RuntimeError):
            await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        document_repo.delete_parse.assert_not_awaited()
        chunk_repo.delete_for_document.assert_not_awaited()

    async def test_a_first_reading_finds_nothing_and_carries_on(self) -> None:
        use_case = _make_use_case(document_repo=_repo_holding([]))

        result = await use_case.execute(
            IngestDocumentCommand(scope=_SCOPE, document=_make_doc())
        )

        assert result.document.status == DocumentStatus.COMPLETED

    async def test_the_crops_of_the_earlier_reading_are_removed_from_storage(self) -> None:
        """A new reading mints new figure ids and so writes to new keys. Skipping this
        does not overwrite the old images, it strands them."""
        figure = _previous_figure()
        storage = _storage_with_a_pdf()
        use_case = _make_use_case(document_repo=_repo_holding([figure]), storage=storage)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        storage.delete.assert_awaited_once_with(figure.crop_key)

    async def test_crops_are_removed_before_the_rows_that_name_them(self) -> None:
        """Those rows hold the only record that the objects exist."""
        document_repo = _repo_holding([_previous_figure()])
        storage = _storage_with_a_pdf()
        order: list[str] = []
        storage.delete.side_effect = lambda *_a, **_k: order.append("crops")
        document_repo.delete_parse.side_effect = lambda *_a, **_k: order.append("rows")
        use_case = _make_use_case(document_repo=document_repo, storage=storage)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        assert order.index("crops") < order.index("rows")

    async def test_a_figure_that_was_never_cropped_is_passed_over(self) -> None:
        storage = _storage_with_a_pdf()
        use_case = _make_use_case(
            document_repo=_repo_holding([_previous_figure(crop_key=None)]), storage=storage
        )

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        storage.delete.assert_not_awaited()

    async def test_a_crop_that_cannot_be_deleted_does_not_stop_the_reading(self) -> None:
        """The object it could not remove costs storage and nothing else — the row
        naming it is about to go either way. Failing here would cost the document."""
        storage = _storage_with_a_pdf()
        storage.delete = AsyncMock(side_effect=RuntimeError("bucket unreachable"))
        use_case = _make_use_case(
            document_repo=_repo_holding([_previous_figure()]), storage=storage
        )

        result = await use_case.execute(
            IngestDocumentCommand(scope=_SCOPE, document=_make_doc())
        )

        assert result.document.status == DocumentStatus.COMPLETED

    async def test_one_failed_crop_delete_does_not_strand_the_rest(self) -> None:
        first, second = _previous_figure(), _previous_figure(crop_key="figures/u/kb/doc/b.png")
        storage = _storage_with_a_pdf()
        storage.delete = AsyncMock(side_effect=[RuntimeError("gone"), None])
        use_case = _make_use_case(document_repo=_repo_holding([first, second]), storage=storage)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        assert storage.delete.await_args_list[-1].args[0] == second.crop_key


# ---------------------------------------------------------------------------
# Chunk → figure / table ID linkage
# ---------------------------------------------------------------------------


def _parser_and_table() -> tuple[AsyncMock, DocumentTable]:
    """A parser yielding one page with a single table element; also returns the table object."""
    element = DocumentElement(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=_DOC_ID,
        page_number=1,
        element_type=ElementType.TABLE,
        text=UntrustedText("Metal | Density\nAluminium | 2.70"),
        reading_order=0,
        processing_method=ProcessingMethod.NATIVE_TEXT,
        created_at=_NOW,
        bounding_box=_TABLE_BOX,
    )
    table = DocumentTable(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=_DOC_ID,
        source_element_id=element.id,
        page_number=1,
        headers=("Metal", "Density"),
        rows=(("Aluminium", "2.70"),),
        units=(None, "g/cm3"),
        bounding_box=_TABLE_BOX,
        created_at=_NOW,
    )
    parser = AsyncMock()
    parser.parse = AsyncMock(
        return_value=[ParsedPage(page=_page(1), elements=[element], tables=[table])]
    )
    return parser, table


def _parser_and_figure() -> tuple[AsyncMock, DocumentFigure]:
    """A parser yielding one page with a described figure; also returns the figure object."""
    element = DocumentElement(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=_DOC_ID,
        page_number=1,
        element_type=ElementType.FIGURE,
        text=UntrustedText(""),
        reading_order=0,
        processing_method=ProcessingMethod.NATIVE_TEXT,
        created_at=_NOW,
        bounding_box=_FIGURE_BOX,
    )
    figure = DocumentFigure(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=_DOC_ID,
        source_element_id=element.id,
        page_number=1,
        kind=ElementType.FIGURE,
        bounding_box=_FIGURE_BOX,
        created_at=_NOW,
        caption=UntrustedText("Growth curve"),
        description="Shows an S-shaped growth curve over time.",
    )
    parser = AsyncMock()
    parser.parse = AsyncMock(
        return_value=[ParsedPage(page=_page(1), elements=[element], figures=[figure])]
    )
    return parser, figure


class TestChunkFigureAndTableIds:
    """Standalone-element chunks carry a direct pointer to the figure or table row."""

    async def test_table_chunk_carries_the_table_id(self) -> None:
        parser, table = _parser_and_table()
        chunk_repo = _make_chunk_repo()
        use_case = _make_use_case(parser=parser, chunk_repo=chunk_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        written = chunk_repo.save_batch.await_args.args[1]
        table_chunks = [c for c in written if c.chunk_type is ChunkType.TABLE]
        assert table_chunks
        assert all(c.table_id == table.id for c in table_chunks)

    async def test_table_chunk_has_no_figure_id(self) -> None:
        parser, _ = _parser_and_table()
        chunk_repo = _make_chunk_repo()
        use_case = _make_use_case(parser=parser, chunk_repo=chunk_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        written = chunk_repo.save_batch.await_args.args[1]
        table_chunks = [c for c in written if c.chunk_type is ChunkType.TABLE]
        assert all(c.figure_id is None for c in table_chunks)

    async def test_figure_chunk_carries_the_figure_id(self) -> None:
        parser, figure = _parser_and_figure()
        chunk_repo = _make_chunk_repo()
        use_case = _make_use_case(parser=parser, chunk_repo=chunk_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        written = chunk_repo.save_batch.await_args.args[1]
        figure_chunks = [c for c in written if c.chunk_type is ChunkType.FIGURE]
        assert figure_chunks
        assert all(c.figure_id == figure.id for c in figure_chunks)

    async def test_figure_chunk_has_no_table_id(self) -> None:
        parser, _ = _parser_and_figure()
        chunk_repo = _make_chunk_repo()
        use_case = _make_use_case(parser=parser, chunk_repo=chunk_repo)

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        written = chunk_repo.save_batch.await_args.args[1]
        figure_chunks = [c for c in written if c.chunk_type is ChunkType.FIGURE]
        assert all(c.table_id is None for c in figure_chunks)

    async def test_prose_chunk_has_neither_figure_id_nor_table_id(self) -> None:
        chunk_repo = _make_chunk_repo()
        use_case = _make_use_case(
            parser=_make_parser([(1, ["A prose paragraph about biology."])]),
            chunk_repo=chunk_repo,
        )

        await use_case.execute(IngestDocumentCommand(scope=_SCOPE, document=_make_doc()))

        written = chunk_repo.save_batch.await_args.args[1]
        prose_chunks = [c for c in written if c.chunk_type is ChunkType.TEXT]
        assert prose_chunks
        assert all(c.figure_id is None and c.table_id is None for c in prose_chunks)
