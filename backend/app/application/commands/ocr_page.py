"""Use case: OCR one scanned or image-heavy page and persist the results.

The page's kind is already recorded by the ingestion that ran before this job.
This use case renders the page to a PNG, hands it to the OCR adapter, and
replaces whatever elements exist for that page with the newly recognised ones.

Replacing rather than merging is intentional: the adapter mints a fresh UUID
for every element on every run, so saving again would insert a parallel copy
alongside the earlier attempt. Deleting first keeps the table clean for retries.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import structlog

from app.domain.ports.adapters import OcrPort, StoragePort
from app.domain.ports.repositories import DocumentRepository
from app.domain.scope import ScopeContext
from app.infrastructure.rendering.page_renderer import PageRenderer

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class OcrPageCommand:
    scope: ScopeContext
    document_id: UUID
    page_number: int


@dataclass(frozen=True)
class OcrPageResult:
    elements_saved: int


class OcrPageUseCase:
    """Render → recognise → persist for one page.

    The caller (worker) is responsible for:
    - marking the job complete
    - committing the session
    - catching exceptions and transitioning the job to FAILED
    """

    def __init__(
        self,
        document_repo: DocumentRepository,
        storage: StoragePort,
        page_renderer: PageRenderer,
        ocr: OcrPort,
    ) -> None:
        self._document_repo = document_repo
        self._storage = storage
        self._page_renderer = page_renderer
        self._ocr = ocr

    async def execute(self, command: OcrPageCommand) -> OcrPageResult:
        scope = command.scope
        log = _log.bind(
            document_id=str(command.document_id),
            page_number=command.page_number,
        )

        pages = await self._document_repo.get_pages(scope, command.document_id)
        page = next(
            (p for p in pages if p.page_number == command.page_number),
            None,
        )
        if page is None:
            log.warning("ocr_page_not_found")
            return OcrPageResult(elements_saved=0)

        doc = await self._document_repo.get(scope, command.document_id)
        if doc is None:
            log.warning("ocr_document_not_found")
            return OcrPageResult(elements_saved=0)

        pdf_bytes = await self._storage.get(doc.storage_key)
        image = await self._page_renderer.render(
            pdf_bytes,
            page_number=command.page_number,
            document_id=command.document_id,
            scope=scope,
        )

        elements = await self._ocr.extract_text(image, page=page)

        await self._document_repo.delete_page_elements(
            scope, command.document_id, command.page_number
        )
        if elements:
            await self._document_repo.save_elements(scope, elements)

        log.info("ocr_page_completed", elements_saved=len(elements))
        return OcrPageResult(elements_saved=len(elements))
