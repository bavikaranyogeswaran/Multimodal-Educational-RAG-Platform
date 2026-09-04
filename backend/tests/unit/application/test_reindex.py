"""Unit tests for ReindexKnowledgeBaseUseCase.

Ingestion is mocked throughout: what a rebuild does to one document is covered in
`test_ingest_document.py`, and what matters here is which documents it reaches, what it
does when one of them will not read, and when retrieval is moved to the result.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.application.commands.ingest_document import IngestDocumentResult
from app.application.commands.reindex import (
    RebuildUnit,
    ReindexKnowledgeBaseCommand,
    ReindexKnowledgeBaseUseCase,
)
from app.domain.documents.entities import Document
from app.domain.enums import DocumentStatus
from app.domain.errors import InvariantViolationError
from app.domain.knowledge_base.entities import KnowledgeBase
from app.domain.scope import ScopeContext

_NOW = datetime(2026, 8, 25, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)

_OLD_VERSION = 1
_NEW_VERSION = 2


def _make_kb(*, active_index_version: int = _OLD_VERSION) -> KnowledgeBase:
    return KnowledgeBase(
        id=_KB_ID,
        user_id=_USER_ID,
        name="Cloud data science",
        created_at=_NOW,
        updated_at=_NOW,
        active_index_version=active_index_version,
    )


def _make_doc(*, status: DocumentStatus = DocumentStatus.COMPLETED) -> Document:
    doc_id = uuid.uuid4()
    # A failed document must say why, which the entity enforces.
    reason = "an earlier read did not finish" if status is DocumentStatus.FAILED else None
    return Document(
        id=doc_id,
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        filename="lecture.pdf",
        content_type="application/pdf",
        byte_size=1024,
        storage_key=f"{_USER_ID}/{_KB_ID}/{doc_id}/original.pdf",
        created_at=_NOW,
        updated_at=_NOW,
        status=status,
        page_count=12,
        failure_reason=reason,
    )


def _unit_of_work(
    kb_repo: AsyncMock, document_repo: AsyncMock, ingest: AsyncMock
) -> Callable[[], AbstractAsyncContextManager[RebuildUnit]]:
    """The same collaborators every time, over a transaction that is not real.

    What each block commits is the worker's business; what the use case has to get right
    is which work goes in which block, and the count of blocks records that.
    """
    job_repo = AsyncMock()
    job_repo.save = AsyncMock()

    @asynccontextmanager
    async def _unit() -> AsyncIterator[RebuildUnit]:
        _unit.opened += 1  # type: ignore[attr-defined]
        yield RebuildUnit(
            knowledge_bases=kb_repo,
            documents=document_repo,
            ingest=ingest,
            job_repo=job_repo,
        )

    _unit.opened = 0  # type: ignore[attr-defined]
    return _unit


def _make_use_case(
    *,
    kb: KnowledgeBase | None = None,
    documents: list[Document] | None = None,
    kb_repo: AsyncMock | None = None,
    document_repo: AsyncMock | None = None,
    ingest: AsyncMock | None = None,
) -> tuple[ReindexKnowledgeBaseUseCase, AsyncMock, AsyncMock, AsyncMock]:
    kb_repo = kb_repo or AsyncMock()
    kb_repo.get = AsyncMock(return_value=kb if kb is not None else _make_kb())

    document_repo = document_repo or AsyncMock()
    document_repo.list = AsyncMock(
        return_value=documents if documents is not None else [_make_doc()]
    )

    if ingest is None:
        ingest = AsyncMock()
        # Ingestion hands back an IngestDocumentResult wrapping the completed document.
        ingest.execute = AsyncMock(
            side_effect=lambda command: IngestDocumentResult(
                document=command.document.mark_completed(
                    page_count=command.document.page_count or 1, now=_NOW
                ),
                searchable_chunk_ids=(),
            )
        )

    use_case = ReindexKnowledgeBaseUseCase(
        _unit_of_work(kb_repo, document_repo, ingest),
        index_version=_NEW_VERSION,
    )
    return use_case, kb_repo, document_repo, ingest


async def _run(use_case: ReindexKnowledgeBaseUseCase) -> object:
    return await use_case.execute(ReindexKnowledgeBaseCommand(scope=_SCOPE))


# ---------------------------------------------------------------------------
# What gets rebuilt
# ---------------------------------------------------------------------------


class TestWhatGetsRebuilt:
    async def test_every_completed_document_is_read_again(self) -> None:
        documents = [_make_doc() for _ in range(3)]
        use_case, _, _, ingest = _make_use_case(documents=documents)

        result = await _run(use_case)

        assert ingest.execute.await_count == 3
        assert result.rebuilt == 3

    async def test_a_failed_document_is_left_alone(self) -> None:
        """It has no index entry to replace, and re-reading it is a separate decision
        from rebuilding the ones that worked."""
        use_case, _, _, ingest = _make_use_case(documents=[_make_doc(status=DocumentStatus.FAILED)])

        result = await _run(use_case)

        ingest.execute.assert_not_awaited()
        assert result.rebuilt == 0

    async def test_a_document_still_being_read_is_left_alone(self) -> None:
        """Another job is writing those rows. Reading it again from here would put two
        writers on the same document."""
        use_case, _, _, ingest = _make_use_case(
            documents=[_make_doc(status=DocumentStatus.PROCESSING)]
        )

        await _run(use_case)

        ingest.execute.assert_not_awaited()

    async def test_a_document_being_deleted_is_left_alone(self) -> None:
        use_case, _, _, ingest = _make_use_case(
            documents=[_make_doc(status=DocumentStatus.DELETING)]
        )

        await _run(use_case)

        ingest.execute.assert_not_awaited()

    async def test_a_missing_knowledge_base_is_refused(self) -> None:
        use_case, kb_repo, _, _ = _make_use_case()
        kb_repo.get = AsyncMock(return_value=None)

        with pytest.raises(InvariantViolationError):
            await _run(use_case)


# ---------------------------------------------------------------------------
# Moving retrieval to the new index
# ---------------------------------------------------------------------------


class TestActivation:
    async def test_retrieval_moves_to_the_version_that_was_written(self) -> None:
        use_case, kb_repo, _, _ = _make_use_case()

        result = await _run(use_case)

        saved = kb_repo.save.await_args.args[1]
        assert saved.active_index_version == _NEW_VERSION
        assert result.activated is True

    async def test_the_old_version_stays_active_until_every_document_is_done(self) -> None:
        """Answering out of a half-built index is the failure this ordering exists to
        avoid, so nothing may point at the new version while it is still being written."""
        documents = [_make_doc() for _ in range(3)]
        use_case, kb_repo, _, ingest = _make_use_case(documents=documents)
        order: list[str] = []
        kb_repo.save.side_effect = lambda *_a, **_k: order.append("activate")
        original = ingest.execute.side_effect
        ingest.execute.side_effect = lambda command: (
            order.append("rebuild"),
            original(command),
        )[1]

        await _run(use_case)

        assert order == ["rebuild", "rebuild", "rebuild", "activate"]

    async def test_a_rebuild_that_read_nothing_leaves_the_old_version_active(self) -> None:
        """The sweep only runs once a document has been read, so a rebuild that never
        got that far destroyed nothing and the old index is still whole."""
        use_case, kb_repo, _, _ = _make_use_case(documents=[])

        result = await _run(use_case)

        kb_repo.save.assert_not_awaited()
        assert result.activated is False

    async def test_a_partly_failed_rebuild_still_moves_retrieval(self) -> None:
        """The documents that succeeded exist only under the new version. Staying on the
        old one to preserve an index that is no longer complete would strand them."""
        good, bad = _make_doc(), _make_doc()
        use_case, kb_repo, _, ingest = _make_use_case(documents=[good, bad])
        ingest.execute = AsyncMock(
            side_effect=[
                IngestDocumentResult(
                    document=good.mark_processing(now=_NOW).mark_completed(page_count=12, now=_NOW),
                    searchable_chunk_ids=(),
                ),
                RuntimeError("the object store is unreachable"),
            ]
        )

        result = await _run(use_case)

        assert result.rebuilt == 1
        assert result.failed == 1
        assert result.activated is True
        assert kb_repo.save.await_args.args[1].active_index_version == _NEW_VERSION


# ---------------------------------------------------------------------------
# A document that will not read
# ---------------------------------------------------------------------------


class TestFailures:
    async def test_one_bad_document_does_not_stop_the_rest(self) -> None:
        first, second, third = _make_doc(), _make_doc(), _make_doc()
        use_case, _, _, ingest = _make_use_case(documents=[first, second, third])
        ingest.execute = AsyncMock(
            side_effect=[
                RuntimeError("this file is not a PDF"),
                IngestDocumentResult(
                    document=second.mark_processing(now=_NOW).mark_completed(page_count=12, now=_NOW),
                    searchable_chunk_ids=(),
                ),
                IngestDocumentResult(
                    document=third.mark_processing(now=_NOW).mark_completed(page_count=12, now=_NOW),
                    searchable_chunk_ids=(),
                ),
            ]
        )

        result = await _run(use_case)

        assert result.rebuilt == 2
        assert result.failed == 1

    async def test_a_document_that_would_not_read_is_marked_failed(self) -> None:
        """Its old chunks may already be gone. Left completed it would answer nothing
        and say nothing about why."""
        use_case, _, document_repo, ingest = _make_use_case()
        ingest.execute = AsyncMock(side_effect=RuntimeError("this file is not a PDF"))

        await _run(use_case)

        statuses = [call.args[1].status for call in document_repo.save.await_args_list]
        assert statuses[-1] is DocumentStatus.FAILED

    async def test_the_reason_reaches_the_document(self) -> None:
        use_case, _, document_repo, ingest = _make_use_case()
        ingest.execute = AsyncMock(side_effect=RuntimeError("the object store is unreachable"))

        await _run(use_case)

        failed = document_repo.save.await_args_list[-1].args[1]
        assert failed.failure_reason == "the object store is unreachable"

    async def test_a_document_says_it_is_being_read_while_it_is(self) -> None:
        """A rebuild interrupted halfway must not leave a document claiming to be
        finished when its index has quietly gone."""
        use_case, _, document_repo, _ = _make_use_case()

        await _run(use_case)

        statuses = [call.args[1].status for call in document_repo.save.await_args_list]
        assert statuses[0] is DocumentStatus.PROCESSING
        assert statuses[-1] is DocumentStatus.COMPLETED


# ---------------------------------------------------------------------------
# Transaction boundaries
# ---------------------------------------------------------------------------


def _recording_use_case(
    documents: list[Document], *, ingest_raises: bool = False
) -> tuple[ReindexKnowledgeBaseUseCase, list[str]]:
    """A use case whose every commit boundary and write lands in one ordered list."""
    events: list[str] = []

    kb_repo = AsyncMock()
    kb_repo.get = AsyncMock(return_value=_make_kb())
    kb_repo.save = AsyncMock(side_effect=lambda *_a, **_k: events.append("flip"))

    document_repo = AsyncMock()
    document_repo.list = AsyncMock(return_value=documents)
    document_repo.save = AsyncMock(
        side_effect=lambda _scope, doc: events.append(f"save:{doc.status.value}")
    )

    ingest = AsyncMock()
    if ingest_raises:
        ingest.execute = AsyncMock(side_effect=lambda _c: (events.append("read"), _raise())[0])
    else:
        ingest.execute = AsyncMock(
            side_effect=lambda command: (
                events.append("read"),
                IngestDocumentResult(
                    document=command.document.mark_completed(page_count=12, now=_NOW),
                    searchable_chunk_ids=(),
                ),
            )[1]
        )

    @asynccontextmanager
    async def _unit() -> AsyncIterator[RebuildUnit]:
        events.append("begin")
        job_repo = AsyncMock()
        job_repo.save = AsyncMock()
        yield RebuildUnit(
            knowledge_bases=kb_repo,
            documents=document_repo,
            ingest=ingest,
            job_repo=job_repo,
        )
        events.append("commit")

    return (
        ReindexKnowledgeBaseUseCase(_unit, index_version=_NEW_VERSION),
        events,
    )


def _raise() -> None:
    raise RuntimeError("this file is not a PDF")


class TestTransactionBoundaries:
    """A rebuild runs for as long as it takes to read a library.

    Held in one transaction, a failure hours in discards every document that had already
    worked, and nothing it wrote is visible until it is all over — including the mark
    that says which document is being read right now.
    """

    async def test_the_processing_mark_is_committed_before_the_reading_starts(self) -> None:
        """Written in the same transaction as the reading it precedes, it would only
        become visible once the reading was over — which is when it stops being true."""
        use_case, events = _recording_use_case([_make_doc()])

        await _run(use_case)

        marked = events.index("save:PROCESSING")
        read = events.index("read")
        assert "commit" in events[marked:read]

    async def test_each_document_is_committed_as_it_finishes(self) -> None:
        """The second document's reading must not be able to discard the first."""
        use_case, events = _recording_use_case([_make_doc(), _make_doc()])

        await _run(use_case)

        first, second = [i for i, e in enumerate(events) if e == "read"]
        assert "commit" in events[first:second]

    async def test_the_flip_is_committed_too(self) -> None:
        use_case, events = _recording_use_case([_make_doc()])

        await _run(use_case)

        assert events[events.index("flip") + 1] == "commit"

    async def test_a_failed_reading_does_not_carry_off_the_mark_that_records_it(self) -> None:
        """The failure is written in a block of its own, after the one that raised, so
        the rollback that discards the half-written index does not discard the record."""
        use_case, events = _recording_use_case([_make_doc()], ingest_raises=True)

        await _run(use_case)

        assert events[-2:] == ["save:FAILED", "commit"]

    async def test_a_reading_that_raises_leaves_its_own_block_uncommitted(self) -> None:
        use_case, events = _recording_use_case([_make_doc()], ingest_raises=True)

        await _run(use_case)

        read = events.index("read")
        # The block the reading ran in never reaches its commit; the next thing that
        # happens is a new block opening to record the failure.
        assert events[read + 1] == "begin"


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


class TestCacheInvalidation:
    async def test_cache_is_swept_when_rebuild_activates(self) -> None:
        cache = AsyncMock()
        use_case, _, _, _ = _make_use_case()
        use_case._cache = cache  # inject after construction

        await _run(use_case)

        cache.delete_by_prefix.assert_awaited_once_with(f"answer:{_KB_ID}:")

    async def test_cache_is_not_swept_when_nothing_was_rebuilt(self) -> None:
        """An empty KB means no documents were read, so the old index is still intact
        and there is no stale data to invalidate."""
        cache = AsyncMock()
        use_case, _, _, _ = _make_use_case(documents=[])
        use_case._cache = cache

        await _run(use_case)

        cache.delete_by_prefix.assert_not_awaited()

    async def test_cache_not_required(self) -> None:
        """cache=None (the default) must not raise."""
        use_case, _, _, _ = _make_use_case()
        await _run(use_case)
