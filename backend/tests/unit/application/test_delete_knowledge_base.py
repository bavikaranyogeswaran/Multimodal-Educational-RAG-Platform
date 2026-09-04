"""Unit tests for DeleteKnowledgeBaseUseCase.

The use case receives the list of documents that existed at deletion time via the
command (the DB rows are already gone by the time the job runs) and removes the
physical objects — stored files and cached renders — for each one.

Key properties under test:
  - each document's renders are discarded and its file deleted
  - a failure on one document does not stop the others (best-effort sweep)
  - an empty document list succeeds and contacts neither port
  - the use case never touches the database (it has no repo dependency)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.application.commands.delete_knowledge_base import (
    DeleteKnowledgeBaseCommand,
    DeleteKnowledgeBaseUseCase,
    DocumentCleanupRecord,
)
from app.domain.scope import ScopeContext

_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)


def _record(*, page_count: int = 5) -> DocumentCleanupRecord:
    doc_id = uuid.uuid4()
    return DocumentCleanupRecord(
        document_id=doc_id,
        storage_key=f"{_USER_ID}/{_KB_ID}/{doc_id}/original.pdf",
        page_count=page_count,
    )


def _use_case(
    *,
    storage: AsyncMock | None = None,
    page_renderer: AsyncMock | None = None,
) -> tuple[DeleteKnowledgeBaseUseCase, AsyncMock, AsyncMock]:
    storage = storage or AsyncMock()
    page_renderer = page_renderer or AsyncMock()
    return (
        DeleteKnowledgeBaseUseCase(storage=storage, page_renderer=page_renderer),
        storage,
        page_renderer,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestCleanup:
    async def test_stored_file_is_removed_for_each_document(self) -> None:
        doc = _record()
        use_case, storage, _ = _use_case()
        await use_case.execute(DeleteKnowledgeBaseCommand(scope=_SCOPE, documents=(doc,)))
        storage.delete.assert_awaited_once_with(doc.storage_key)

    async def test_cached_renders_are_discarded_for_each_document(self) -> None:
        doc = _record(page_count=7)
        use_case, _, renderer = _use_case()
        await use_case.execute(DeleteKnowledgeBaseCommand(scope=_SCOPE, documents=(doc,)))
        renderer.discard_document.assert_awaited_once()
        assert renderer.discard_document.call_args.kwargs["page_count"] == 7

    async def test_all_documents_are_cleaned_up(self) -> None:
        docs = tuple(_record() for _ in range(4))
        use_case, storage, renderer = _use_case()
        await use_case.execute(DeleteKnowledgeBaseCommand(scope=_SCOPE, documents=docs))
        assert storage.delete.await_count == 4
        assert renderer.discard_document.await_count == 4

    async def test_scope_is_forwarded_to_renderer(self) -> None:
        doc = _record()
        use_case, _, renderer = _use_case()
        await use_case.execute(DeleteKnowledgeBaseCommand(scope=_SCOPE, documents=(doc,)))
        assert renderer.discard_document.call_args.kwargs["scope"] is _SCOPE


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    async def test_empty_document_list_succeeds(self) -> None:
        use_case, storage, renderer = _use_case()
        await use_case.execute(DeleteKnowledgeBaseCommand(scope=_SCOPE, documents=()))
        storage.delete.assert_not_awaited()
        renderer.discard_document.assert_not_awaited()

    async def test_zero_page_count_does_not_raise(self) -> None:
        doc = _record(page_count=0)
        use_case, _, _ = _use_case()
        await use_case.execute(DeleteKnowledgeBaseCommand(scope=_SCOPE, documents=(doc,)))


# ---------------------------------------------------------------------------
# Fault tolerance — one failure must not cancel the rest
# ---------------------------------------------------------------------------


class TestFaultTolerance:
    async def test_render_failure_does_not_stop_file_deletion(self) -> None:
        doc = _record()
        renderer = AsyncMock()
        renderer.discard_document = AsyncMock(side_effect=RuntimeError("render cache unavailable"))
        use_case, storage, _ = _use_case(page_renderer=renderer)
        await use_case.execute(DeleteKnowledgeBaseCommand(scope=_SCOPE, documents=(doc,)))
        storage.delete.assert_awaited_once_with(doc.storage_key)

    async def test_storage_failure_on_one_does_not_stop_the_next(self) -> None:
        first, second = _record(), _record()
        storage = AsyncMock()
        storage.delete = AsyncMock(
            side_effect=[RuntimeError("object store unreachable"), None]
        )
        use_case, _, renderer = _use_case(storage=storage)
        await use_case.execute(
            DeleteKnowledgeBaseCommand(scope=_SCOPE, documents=(first, second))
        )
        assert storage.delete.await_count == 2
        assert renderer.discard_document.await_count == 2

    async def test_render_failure_on_one_does_not_stop_the_next(self) -> None:
        first, second = _record(), _record()
        renderer = AsyncMock()
        renderer.discard_document = AsyncMock(
            side_effect=[RuntimeError("cache timeout"), None]
        )
        use_case, storage, _ = _use_case(page_renderer=renderer)
        await use_case.execute(
            DeleteKnowledgeBaseCommand(scope=_SCOPE, documents=(first, second))
        )
        assert storage.delete.await_count == 2
