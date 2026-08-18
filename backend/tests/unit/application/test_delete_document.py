"""Unit tests for DeleteDocumentUseCase.

Deletion has to be safe to repeat. A job that fails halfway is retried, and the second
run meets work the first one finished: a file already removed, renders that were never
written, a row that has gone. None of that is an error, and a handler that treated it as
one would retry until it dead-lettered over work that was already done.

The other property under test is ordering. Renders are addressed per page and the page
count lives on the row, so removing the row first would leave every cached image
unreachable — sitting in the cache until its lifetime ran out, belonging to nothing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from app.application.commands.delete_document import (
    DeleteDocumentCommand,
    DeleteDocumentUseCase,
)
from app.domain.documents.entities import Document
from app.domain.enums import DocumentStatus
from app.domain.scope import ScopeContext

_NOW = datetime(2025, 6, 1, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_DOC_ID = uuid.uuid4()
_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)
_STORAGE_KEY = f"{_USER_ID}/{_KB_ID}/{_DOC_ID}/original.pdf"

_COMMAND = DeleteDocumentCommand(
    scope=_SCOPE, document_id=_DOC_ID, storage_key=_STORAGE_KEY
)


def _document(*, page_count: int | None = 3) -> Document:
    return Document(
        id=_DOC_ID,
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        filename="lecture.pdf",
        content_type="application/pdf",
        byte_size=2048,
        storage_key=_STORAGE_KEY,
        created_at=_NOW,
        updated_at=_NOW,
        status=DocumentStatus.DELETING,
        page_count=page_count,
    )


def _repo(document: Document | None) -> AsyncMock:
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=document)
    repo.delete = AsyncMock()
    return repo


# Distinguishes "caller did not say" from "caller said there is no document", which
# a None default cannot — and the difference is the whole point of half these tests.
_UNSET = object()


def _use_case(
    *,
    document: Document | object | None = _UNSET,
    repo: AsyncMock | None = None,
    storage: AsyncMock | None = None,
    renderer: AsyncMock | None = None,
) -> tuple[DeleteDocumentUseCase, AsyncMock, AsyncMock, AsyncMock]:
    resolved = _document() if document is _UNSET else document
    document_repo = repo or _repo(resolved)  # type: ignore[arg-type]
    store = storage or AsyncMock()
    render = renderer or AsyncMock()
    use_case = DeleteDocumentUseCase(
        document_repo=document_repo, storage=store, page_renderer=render
    )
    return use_case, document_repo, store, render


# ---------------------------------------------------------------------------
# What gets removed
# ---------------------------------------------------------------------------


class TestRemoval:
    async def test_the_stored_original_is_removed(self) -> None:
        use_case, _, storage, _ = _use_case()
        await use_case.execute(_COMMAND)
        storage.delete.assert_awaited_once_with(_STORAGE_KEY)

    async def test_the_cached_renders_are_removed(self) -> None:
        use_case, _, _, renderer = _use_case()
        await use_case.execute(_COMMAND)
        renderer.discard_document.assert_awaited_once()

    async def test_every_page_of_renders_is_covered(self) -> None:
        use_case, _, _, renderer = _use_case(document=_document(page_count=7))
        await use_case.execute(_COMMAND)
        assert renderer.discard_document.call_args.kwargs["page_count"] == 7

    async def test_the_row_is_removed(self) -> None:
        use_case, repo, _, _ = _use_case()
        await use_case.execute(_COMMAND)
        repo.delete.assert_awaited_once_with(_SCOPE, _DOC_ID)

    async def test_everything_is_scoped_to_the_caller(self) -> None:
        use_case, repo, _, renderer = _use_case()
        await use_case.execute(_COMMAND)
        assert repo.get.call_args.args[0] == _SCOPE
        assert renderer.discard_document.call_args.kwargs["scope"] == _SCOPE


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


class TestOrdering:
    async def test_renders_are_discarded_before_the_row_goes(self) -> None:
        """The page count lives on the row. Delete it first and nothing knows how many
        cached images to look for, so they sit in the cache until they expire."""
        order: list[str] = []
        repo = _repo(_document())
        repo.delete = AsyncMock(side_effect=lambda *_a, **_k: order.append("row"))
        renderer = AsyncMock()
        renderer.discard_document = AsyncMock(
            side_effect=lambda *_a, **_k: order.append("renders")
        )

        use_case, _, _, _ = _use_case(repo=repo, renderer=renderer)
        await use_case.execute(_COMMAND)

        assert order == ["renders", "row"]

    async def test_the_file_is_removed_before_the_row_goes(self) -> None:
        """The row is what says where the file is. The key is carried on the job, so
        this is not strictly required — but a row that outlives its file describes
        something that is not there, which is the worse of the two orders to fail in."""
        order: list[str] = []
        repo = _repo(_document())
        repo.delete = AsyncMock(side_effect=lambda *_a, **_k: order.append("row"))
        storage = AsyncMock()
        storage.delete = AsyncMock(side_effect=lambda *_a, **_k: order.append("file"))

        use_case, _, _, _ = _use_case(repo=repo, storage=storage)
        await use_case.execute(_COMMAND)

        assert order == ["file", "row"]


# ---------------------------------------------------------------------------
# Repeating a deletion
# ---------------------------------------------------------------------------


class TestRepeatedDeletion:
    async def test_an_already_deleted_document_succeeds(self) -> None:
        """This is the outcome the job exists to produce. Failing here would retry the
        job until it dead-lettered over work that was already done."""
        use_case, _, _, _ = _use_case(document=None)
        await use_case.execute(_COMMAND)

    async def test_nothing_is_removed_twice(self) -> None:
        use_case, repo, storage, renderer = _use_case(document=None)
        await use_case.execute(_COMMAND)
        storage.delete.assert_not_awaited()
        renderer.discard_document.assert_not_awaited()
        repo.delete.assert_not_awaited()

    async def test_running_twice_is_safe(self) -> None:
        """A retry after a partial failure meets a mixture of done and not done."""
        repo = _repo(_document())
        use_case, _, storage, _ = _use_case(repo=repo)

        await use_case.execute(_COMMAND)
        repo.get = AsyncMock(return_value=None)  # the first run removed it
        await use_case.execute(_COMMAND)

        assert storage.delete.await_count == 1


# ---------------------------------------------------------------------------
# Documents with nothing to discard
# ---------------------------------------------------------------------------


class TestDegenerateDocuments:
    async def test_a_document_with_no_page_count_still_deletes(self) -> None:
        """Page count is null until ingestion completes, so a document deleted while
        still pending has none — and still has a file and a row to remove."""
        use_case, repo, storage, renderer = _use_case(document=_document(page_count=None))
        await use_case.execute(_COMMAND)

        assert renderer.discard_document.call_args.kwargs["page_count"] == 0
        storage.delete.assert_awaited_once()
        repo.delete.assert_awaited_once()
