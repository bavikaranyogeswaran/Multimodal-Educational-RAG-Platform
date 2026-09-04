"""Use case: clean up the physical objects of a deleted Knowledge Base.

The database rows are removed by the API request itself — the knowledge_base
cascade takes all documents, pages, chunks and conversations with it. What
remains after that are:
  - the original PDF files in object storage
  - the cached page-render images in the render cache

The command carries every document record that existed at the moment of deletion
so that the job can do its work without querying the database, whose rows are
already gone.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import structlog

from app.domain.ports.adapters import PageRendererPort, StoragePort
from app.domain.scope import ScopeContext

_log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DocumentCleanupRecord:
    """The minimum information needed to purge one document's physical objects."""

    document_id: UUID
    storage_key: str
    page_count: int


@dataclass(frozen=True)
class DeleteKnowledgeBaseCommand:
    scope: ScopeContext
    documents: tuple[DocumentCleanupRecord, ...]


class DeleteKnowledgeBaseUseCase:
    """Remove every document's stored file and cached renders for a deleted KB."""

    def __init__(
        self,
        storage: StoragePort,
        page_renderer: PageRendererPort,
    ) -> None:
        self._storage = storage
        self._page_renderer = page_renderer

    async def execute(self, command: DeleteKnowledgeBaseCommand) -> None:
        scope = command.scope
        log = _log.bind(
            knowledge_base_id=str(scope.knowledge_base_id),
            document_count=len(command.documents),
        )
        log.info("kb_cleanup_started")

        for doc in command.documents:
            # Cached renders first — they are addressed by page and the page count
            # is what tells us how many to look for. Both steps are idempotent so a
            # partial failure on a previous attempt leaves nothing broken.
            try:
                await self._page_renderer.discard_document(
                    document_id=doc.document_id,
                    scope=scope,
                    page_count=doc.page_count,
                )
            except Exception:
                _log.exception(
                    "kb_cleanup_render_failed",
                    document_id=str(doc.document_id),
                )

            try:
                await self._storage.delete(doc.storage_key)
            except Exception:
                _log.exception(
                    "kb_cleanup_storage_failed",
                    storage_key=doc.storage_key,
                )

        log.info("kb_cleanup_finished")
