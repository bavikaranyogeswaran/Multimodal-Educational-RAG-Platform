"""Use case: finish removing a document a student asked to have deleted.

Deletion is asynchronous because it spans more than the database. The endpoint marks the
document `DELETING` and returns, which blocks retrieval immediately — that much is
instant, and it is the part that matters for not showing someone content they have
removed. What remains is the slower half: the original file, the cached page renders, and
the row itself.

Most of the database follows on its own. Chunks, elements and pages are all owned by the
document row and cascade when it goes. Graph entities deliberately do not: their link to
a source document is cleared rather than followed, because an entity supported by several
documents survives the loss of one of them.

Every step is written to be safe when repeated. A deletion job can be retried after a
partial failure, and the second run finds some of the work already done — a file that is
already gone, renders that were never written, a row that no longer exists. None of that
is an error. Deleting something twice and deleting something that was never there both
mean the same thing here: it is not there now.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import structlog

from app.domain.ports.adapters import CacheStore, PageRendererPort, StoragePort
from app.domain.ports.repositories import DocumentRepository
from app.domain.scope import ScopeContext

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DeleteDocumentCommand:
    scope: ScopeContext
    document_id: UUID
    #: Carried on the job rather than read back, so the original can still be removed
    #: after the row describing where it lives has gone.
    storage_key: str


class DeleteDocumentUseCase:
    """Remove a document's file, its cached renders, and its row."""

    def __init__(
        self,
        document_repo: DocumentRepository,
        storage: StoragePort,
        page_renderer: PageRendererPort,
        cache: CacheStore | None = None,
    ) -> None:
        self._document_repo = document_repo
        self._storage = storage
        self._page_renderer = page_renderer
        self._cache = cache

    async def execute(self, command: DeleteDocumentCommand) -> None:
        scope = command.scope
        document = await self._document_repo.get(scope, command.document_id)

        # A document that is already gone is the outcome this job exists to produce. It
        # happens when a job is retried after succeeding, or when the Knowledge Base was
        # deleted first and took the row with it. Either way there is nothing to do, and
        # failing here would retry the job until it dead-lettered over work already done.
        if document is None:
            _log.info("document_already_deleted", document_id=str(command.document_id))
            return

        # Renders first. They are addressed by page, and the page count is on the row
        # that is about to be deleted — after that, nothing would know how many to look
        # for, and every cached image would sit in the cache until its lifetime ran out.
        await self._page_renderer.discard_document(
            document_id=command.document_id,
            scope=scope,
            page_count=document.page_count or 0,
        )

        await self._storage.delete(command.storage_key)

        # Last, because it is what the rest is reachable from. Chunks, elements and pages
        # go with it; graph entities keep their rows with the link cleared.
        await self._document_repo.delete(scope, command.document_id)

        if self._cache is not None:
            try:
                await self._cache.delete_by_prefix(f"answer:{scope.knowledge_base_id}:")
            except Exception:
                _log.exception(
                    "document_cache_invalidation_failed",
                    document_id=str(command.document_id),
                )

        _log.info(
            "document_deleted",
            document_id=str(command.document_id),
            pages=document.page_count or 0,
        )
