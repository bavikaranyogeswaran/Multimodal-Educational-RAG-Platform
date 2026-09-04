"""Unit tests for OcrPageUseCase.

The use case stitches four collaborators together: the document repository,
object storage, the page renderer, and the OCR adapter. Every collaborator is
mocked so the tests run without any infrastructure and stay fast.

The three things the tests verify are:
  1. The full happy path: storage is consulted, the renderer is called, the
     OCR adapter receives the rendered image, and the resulting elements are
     written.
  2. Guard clauses: a missing page or document returns an empty result without
     touching storage or the OCR adapter.
  3. Idempotency: existing elements for the page are deleted before the new
     ones are saved, so re-running the job does not accumulate duplicates.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.commands.ocr_page import OcrPageCommand, OcrPageUseCase
from app.domain.documents.entities import Document, DocumentElement, DocumentPage
from app.domain.enums import (
    DocumentStatus,
    ElementType,
    PageKind,
    ProcessingMethod,
)
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _document(scope: ScopeContext, *, storage_key: str = "uploads/test.pdf") -> Document:
    now = datetime.now(UTC)
    return Document(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        filename="test.pdf",
        content_type="application/pdf",
        byte_size=1024,
        storage_key=storage_key,
        created_at=now,
        updated_at=now,
        status=DocumentStatus.PROCESSING,
    )


def _page(
    scope: ScopeContext,
    *,
    document_id: uuid.UUID,
    page_number: int = 1,
    kind: PageKind = PageKind.SCANNED,
) -> DocumentPage:
    return DocumentPage(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        document_id=document_id,
        page_number=page_number,
        kind=kind,
        width=595.0,
        height=841.0,
    )


def _element(scope: ScopeContext, *, document_id: uuid.UUID, page_number: int = 1) -> DocumentElement:
    from app.domain.documents.entities import BoundingBox
    now = datetime.now(UTC)
    return DocumentElement(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        document_id=document_id,
        page_number=page_number,
        element_type=ElementType.PARAGRAPH,
        text=UntrustedText("recognised text"),
        reading_order=0,
        processing_method=ProcessingMethod.OCR,
        created_at=now,
        bounding_box=BoundingBox(x0=0.0, y0=10.0, x1=100.0, y1=20.0),
        confidence=0.9,
    )


def _make_use_case(
    *,
    pages: list[DocumentPage] | None = None,
    document: Document | None = None,
    pdf_bytes: bytes = b"pdf",
    image_bytes: bytes = b"png",
    ocr_elements: list | None = None,
) -> tuple[OcrPageUseCase, MagicMock, MagicMock, MagicMock, MagicMock]:
    doc_repo = AsyncMock()
    doc_repo.get_pages = AsyncMock(return_value=pages or [])
    doc_repo.get = AsyncMock(return_value=document)
    doc_repo.delete_page_elements = AsyncMock()
    doc_repo.save_elements = AsyncMock()

    storage = AsyncMock()
    storage.get = AsyncMock(return_value=pdf_bytes)

    renderer = AsyncMock()
    renderer.render = AsyncMock(return_value=image_bytes)

    ocr = AsyncMock()
    ocr.extract_text = AsyncMock(return_value=ocr_elements or [])

    uc = OcrPageUseCase(
        document_repo=doc_repo,
        storage=storage,
        page_renderer=renderer,
        ocr=ocr,
    )
    return uc, doc_repo, storage, renderer, ocr


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_returns_element_count() -> None:
    scope = _scope()
    doc = _document(scope)
    page = _page(scope, document_id=doc.id)
    el = _element(scope, document_id=doc.id)
    uc, *_ = _make_use_case(pages=[page], document=doc, ocr_elements=[el])

    result = await uc.execute(OcrPageCommand(scope=scope, document_id=doc.id, page_number=1))

    assert result.elements_saved == 1


@pytest.mark.asyncio
async def test_storage_is_called_with_document_key() -> None:
    scope = _scope()
    doc = _document(scope, storage_key="uploads/my.pdf")
    page = _page(scope, document_id=doc.id)
    uc, _, storage, *_ = _make_use_case(pages=[page], document=doc)

    await uc.execute(OcrPageCommand(scope=scope, document_id=doc.id, page_number=1))

    storage.get.assert_called_once_with("uploads/my.pdf")


@pytest.mark.asyncio
async def test_renderer_receives_pdf_bytes_and_page_number() -> None:
    scope = _scope()
    doc = _document(scope)
    page = _page(scope, document_id=doc.id, page_number=3)
    uc, _, _, renderer, _ = _make_use_case(pages=[page], document=doc, pdf_bytes=b"raw-pdf")

    await uc.execute(OcrPageCommand(scope=scope, document_id=doc.id, page_number=3))

    renderer.render.assert_called_once_with(
        b"raw-pdf",
        page_number=3,
        document_id=doc.id,
        scope=scope,
    )


@pytest.mark.asyncio
async def test_ocr_receives_rendered_image_and_page() -> None:
    scope = _scope()
    doc = _document(scope)
    page = _page(scope, document_id=doc.id)
    uc, _, _, _, ocr = _make_use_case(pages=[page], document=doc, image_bytes=b"rendered-png")

    await uc.execute(OcrPageCommand(scope=scope, document_id=doc.id, page_number=1))

    ocr.extract_text.assert_called_once_with(b"rendered-png", page=page)


@pytest.mark.asyncio
async def test_elements_are_saved_after_delete() -> None:
    scope = _scope()
    doc = _document(scope)
    page = _page(scope, document_id=doc.id)
    el = _element(scope, document_id=doc.id)
    uc, doc_repo, *_ = _make_use_case(pages=[page], document=doc, ocr_elements=[el])

    await uc.execute(OcrPageCommand(scope=scope, document_id=doc.id, page_number=1))

    doc_repo.delete_page_elements.assert_called_once_with(scope, doc.id, 1)
    doc_repo.save_elements.assert_called_once_with(scope, [el])


@pytest.mark.asyncio
async def test_delete_is_called_before_save() -> None:
    """Idempotency: delete must precede save so retries do not accumulate rows."""
    scope = _scope()
    doc = _document(scope)
    page = _page(scope, document_id=doc.id)
    el = _element(scope, document_id=doc.id)
    uc, doc_repo, *_ = _make_use_case(pages=[page], document=doc, ocr_elements=[el])

    calls: list[str] = []
    doc_repo.delete_page_elements.side_effect = lambda *_: calls.append("delete")
    doc_repo.save_elements.side_effect = lambda *_: calls.append("save")

    await uc.execute(OcrPageCommand(scope=scope, document_id=doc.id, page_number=1))

    assert calls == ["delete", "save"]


# ---------------------------------------------------------------------------
# Guard clauses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_page_returns_zero_and_does_not_call_storage() -> None:
    scope = _scope()
    doc = _document(scope)
    uc, _, storage, renderer, ocr = _make_use_case(pages=[], document=doc)

    result = await uc.execute(OcrPageCommand(scope=scope, document_id=doc.id, page_number=1))

    assert result.elements_saved == 0
    storage.get.assert_not_called()
    renderer.render.assert_not_called()
    ocr.extract_text.assert_not_called()


@pytest.mark.asyncio
async def test_missing_document_returns_zero_and_does_not_call_storage() -> None:
    scope = _scope()
    doc_id = uuid.uuid4()
    page = _page(scope, document_id=doc_id)
    uc, _, storage, renderer, ocr = _make_use_case(pages=[page], document=None)

    result = await uc.execute(OcrPageCommand(scope=scope, document_id=doc_id, page_number=1))

    assert result.elements_saved == 0
    storage.get.assert_not_called()


# ---------------------------------------------------------------------------
# Empty OCR result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_ocr_result_does_not_call_save_elements() -> None:
    scope = _scope()
    doc = _document(scope)
    page = _page(scope, document_id=doc.id)
    uc, doc_repo, *_ = _make_use_case(pages=[page], document=doc, ocr_elements=[])

    result = await uc.execute(OcrPageCommand(scope=scope, document_id=doc.id, page_number=1))

    assert result.elements_saved == 0
    doc_repo.delete_page_elements.assert_called_once()
    doc_repo.save_elements.assert_not_called()
