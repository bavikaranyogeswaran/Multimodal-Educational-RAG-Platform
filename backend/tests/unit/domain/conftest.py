"""Builders for domain entities.

Each takes the fields a test actually cares about and fills the rest with something valid,
so a test reads as the one thing it is checking rather than as twelve lines of scaffolding.

The builders are typed rather than left as bare callables: these tests are type-checked
too, and an untyped factory would silently switch that off for every test that uses one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

import pytest

from app.domain.documents.entities import Document, DocumentElement, DocumentPage
from app.domain.enums import ElementType, PageKind, ProcessingMethod
from app.domain.knowledge_base.entities import KnowledgeBase
from app.domain.scope import ScopeContext
from app.domain.values import BoundingBox, UntrustedText

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 8, 2, 13, 0, tzinfo=UTC)


class Builder[T](Protocol):
    """Constructs an entity, overriding only the fields a test names."""

    def __call__(self, **overrides: Any) -> T: ...


@pytest.fixture
def scope() -> ScopeContext:
    return ScopeContext(user_id=uuid4(), knowledge_base_id=uuid4())


@pytest.fixture
def make_knowledge_base() -> Builder[KnowledgeBase]:
    def build(**overrides: Any) -> KnowledgeBase:
        defaults: dict[str, Any] = {
            "id": uuid4(),
            "user_id": uuid4(),
            "name": "Biology Final Examination",
            "created_at": NOW,
            "updated_at": NOW,
        }
        return KnowledgeBase(**{**defaults, **overrides})

    return build


@pytest.fixture
def make_document(scope: ScopeContext) -> Builder[Document]:
    def build(**overrides: Any) -> Document:
        defaults: dict[str, Any] = {
            "id": uuid4(),
            "user_id": scope.user_id,
            "knowledge_base_id": scope.knowledge_base_id,
            "filename": "biology-textbook.pdf",
            "content_type": "application/pdf",
            "byte_size": 4_200_000,
            "storage_key": f"{scope.user_id}/{scope.knowledge_base_id}/doc/original.pdf",
            "created_at": NOW,
            "updated_at": NOW,
        }
        return Document(**{**defaults, **overrides})

    return build


@pytest.fixture
def make_page(scope: ScopeContext) -> Builder[DocumentPage]:
    def build(**overrides: Any) -> DocumentPage:
        defaults: dict[str, Any] = {
            "id": uuid4(),
            "user_id": scope.user_id,
            "knowledge_base_id": scope.knowledge_base_id,
            "document_id": uuid4(),
            "page_number": 67,
            "kind": PageKind.NATIVE_TEXT,
            "width": 595.0,
            "height": 842.0,
        }
        return DocumentPage(**{**defaults, **overrides})

    return build


@pytest.fixture
def make_element(scope: ScopeContext) -> Builder[DocumentElement]:
    def build(**overrides: Any) -> DocumentElement:
        defaults: dict[str, Any] = {
            "id": uuid4(),
            "user_id": scope.user_id,
            "knowledge_base_id": scope.knowledge_base_id,
            "document_id": uuid4(),
            "page_number": 67,
            "element_type": ElementType.PARAGRAPH,
            "text": UntrustedText("The rate plateaus at high light intensity."),
            "reading_order": 3,
            "processing_method": ProcessingMethod.NATIVE_TEXT,
            "created_at": NOW,
        }
        return DocumentElement(**{**defaults, **overrides})

    return build


@pytest.fixture
def ocr_element(make_element: Builder[DocumentElement]) -> Builder[DocumentElement]:
    """An OCR-derived element, which must carry a box and a confidence."""

    def build(**overrides: Any) -> DocumentElement:
        defaults: dict[str, Any] = {
            "processing_method": ProcessingMethod.OCR,
            "bounding_box": BoundingBox(72, 500, 523, 560),
            "confidence": 0.94,
        }
        return make_element(**{**defaults, **overrides})

    return build


def completed(document: Document, *, pages: int = 400) -> Document:
    """Advance a document to COMPLETED through the transitions that lead there."""
    return document.mark_processing(now=NOW).mark_completed(page_count=pages, now=LATER)
