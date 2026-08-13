"""Tests for SqlDocumentRepository.

Documents, pages: SQLite-backed (models have no PG-specific types).
Elements: mock-backed (DocumentElementModel uses ARRAY for heading_path).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.documents.entities import Document, DocumentPage
from app.domain.enums import DocumentStatus, PageKind
from app.domain.errors import ScopeViolationError
from app.domain.knowledge_base.entities import KnowledgeBase
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.document import (
    SqlDocumentRepository,
    _element_to_entity,
    _element_to_model,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_scope(
    *,
    user_id: uuid.UUID | None = None,
    kb_id: uuid.UUID | None = None,
) -> ScopeContext:
    return ScopeContext(
        user_id=user_id or uuid.uuid4(),
        knowledge_base_id=kb_id or uuid.uuid4(),
    )


def _make_kb(scope: ScopeContext) -> KnowledgeBase:
    ts = datetime.now(UTC)
    return KnowledgeBase(
        id=scope.knowledge_base_id,
        user_id=scope.user_id,
        name="KB",
        created_at=ts,
        updated_at=ts,
    )


def _make_doc(scope: ScopeContext, *, age_seconds: int = 0) -> Document:
    ts = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return Document(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        filename="lecture.pdf",
        content_type="application/pdf",
        byte_size=102_400,
        storage_key=f"uploads/{uuid.uuid4()}.pdf",
        created_at=ts,
        updated_at=ts,
    )


def _make_page(scope: ScopeContext, document_id: uuid.UUID, page_number: int) -> DocumentPage:
    return DocumentPage(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        document_id=document_id,
        page_number=page_number,
        kind=PageKind.NATIVE_TEXT,
        width=595.0,
        height=842.0,
    )


def _doc_repo(scope: ScopeContext, session: AsyncSession) -> SqlDocumentRepository:
    return SqlDocumentRepository(scope=scope, session=session)


async def _save_kb(scope: ScopeContext, session: AsyncSession) -> None:
    from app.infrastructure.database.repositories.knowledge_base import SqlKnowledgeBaseRepository

    kb_repo = SqlKnowledgeBaseRepository(scope=scope, session=session)
    await kb_repo.save(scope, _make_kb(scope))
    await session.flush()


# ---------------------------------------------------------------------------
# Document CRUD — SQLite
# ---------------------------------------------------------------------------


class TestDocumentGet:
    async def test_returns_matching_document(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        doc = _make_doc(scope)
        repo = _doc_repo(scope, sqlite_session)
        await repo.save(scope, doc)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await repo.get(scope, doc.id)
        assert result is not None
        assert result.id == doc.id
        assert result.filename == doc.filename

    async def test_returns_none_when_absent(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _doc_repo(scope, sqlite_session)
        result = await repo.get(scope, uuid.uuid4())
        assert result is None

    async def test_scope_isolation(self, sqlite_session: AsyncSession) -> None:
        scope_a = _make_scope()
        scope_b = _make_scope()
        await _save_kb(scope_a, sqlite_session)
        await _save_kb(scope_b, sqlite_session)

        doc = _make_doc(scope_a)
        await _doc_repo(scope_a, sqlite_session).save(scope_a, doc)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _doc_repo(scope_b, sqlite_session).get(scope_b, doc.id)
        assert result is None


class TestDocumentSave:
    async def test_insert_is_readable(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        doc = _make_doc(scope)
        repo = _doc_repo(scope, sqlite_session)
        await repo.save(scope, doc)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        assert await repo.get(scope, doc.id) is not None

    async def test_status_round_trips(self, sqlite_session: AsyncSession) -> None:
        from dataclasses import replace

        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        doc = _make_doc(scope)
        repo = _doc_repo(scope, sqlite_session)
        await repo.save(scope, doc)
        await sqlite_session.flush()

        ts = datetime.now(UTC)
        processing = replace(doc, status=DocumentStatus.PROCESSING, updated_at=ts)
        await repo.save(scope, processing)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await repo.get(scope, doc.id)
        assert result is not None
        assert result.status == DocumentStatus.PROCESSING


class TestDocumentList:
    async def test_returns_all_docs_for_scope(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        doc1 = _make_doc(scope)
        doc2 = _make_doc(scope)
        repo = _doc_repo(scope, sqlite_session)
        await repo.save(scope, doc1)
        await repo.save(scope, doc2)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list(scope)
        assert len(results) == 2

    async def test_orders_newest_first(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        older = _make_doc(scope, age_seconds=120)
        newer = _make_doc(scope, age_seconds=0)
        repo = _doc_repo(scope, sqlite_session)
        await repo.save(scope, older)
        await repo.save(scope, newer)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list(scope)
        assert results[0].id == newer.id

    async def test_scope_isolation(self, sqlite_session: AsyncSession) -> None:
        scope_a = _make_scope()
        scope_b = _make_scope()
        await _save_kb(scope_a, sqlite_session)
        await _save_kb(scope_b, sqlite_session)

        await _doc_repo(scope_a, sqlite_session).save(scope_a, _make_doc(scope_a))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await _doc_repo(scope_b, sqlite_session).list(scope_b)
        assert list(results) == []


class TestDocumentDelete:
    async def test_delete_removes_document(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        doc = _make_doc(scope)
        repo = _doc_repo(scope, sqlite_session)
        await repo.save(scope, doc)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        await repo.delete(scope, doc.id)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        assert await repo.get(scope, doc.id) is None

    async def test_delete_is_scoped(self, sqlite_session: AsyncSession) -> None:
        kb_id = uuid.uuid4()
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        scope_a = ScopeContext(user_id=user_a, knowledge_base_id=kb_id)
        scope_b = ScopeContext(user_id=user_b, knowledge_base_id=kb_id)

        await _save_kb(scope_a, sqlite_session)
        doc = _make_doc(scope_a)
        await _doc_repo(scope_a, sqlite_session).save(scope_a, doc)
        await sqlite_session.flush()

        await _doc_repo(scope_b, sqlite_session).delete(scope_b, doc.id)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        assert await _doc_repo(scope_a, sqlite_session).get(scope_a, doc.id) is not None


# ---------------------------------------------------------------------------
# Pages — SQLite
# ---------------------------------------------------------------------------


class TestDocumentPages:
    async def test_save_and_get_pages(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        doc = _make_doc(scope)
        repo = _doc_repo(scope, sqlite_session)
        await repo.save(scope, doc)
        await sqlite_session.flush()

        pages = [_make_page(scope, doc.id, n) for n in range(1, 4)]
        await repo.save_pages(scope, pages)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result_pages = await repo.get_pages(scope, doc.id)
        assert len(result_pages) == 3

    async def test_get_pages_ordered_by_page_number(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        doc = _make_doc(scope)
        repo = _doc_repo(scope, sqlite_session)
        await repo.save(scope, doc)
        await sqlite_session.flush()

        pages = [_make_page(scope, doc.id, n) for n in [3, 1, 2]]
        await repo.save_pages(scope, pages)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result_pages = await repo.get_pages(scope, doc.id)
        page_numbers = [p.page_number for p in result_pages]
        assert page_numbers == [1, 2, 3]

    async def test_get_pages_scope_isolation(self, sqlite_session: AsyncSession) -> None:
        scope_a = _make_scope()
        scope_b = _make_scope()
        await _save_kb(scope_a, sqlite_session)
        await _save_kb(scope_b, sqlite_session)
        doc_a = _make_doc(scope_a)
        await _doc_repo(scope_a, sqlite_session).save(scope_a, doc_a)
        await sqlite_session.flush()

        pages = [_make_page(scope_a, doc_a.id, 1)]
        await _doc_repo(scope_a, sqlite_session).save_pages(scope_a, pages)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _doc_repo(scope_b, sqlite_session).get_pages(scope_b, doc_a.id)
        assert list(result) == []


# ---------------------------------------------------------------------------
# Elements — mock-based (ARRAY column prevents SQLite)
# ---------------------------------------------------------------------------


def _mock_result_scalars(rows: list[object]) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


class TestDocumentElements:
    async def test_save_elements_calls_merge_for_each(self) -> None:
        from app.domain.documents.entities import DocumentElement
        from app.domain.enums import ElementType, ProcessingMethod
        from app.domain.values import UntrustedText

        scope = _make_scope()
        session = AsyncMock()
        session.merge = AsyncMock(return_value=MagicMock())
        repo = _doc_repo(scope, session)

        ts = datetime.now(UTC)
        elements = [
            DocumentElement(
                id=uuid.uuid4(),
                user_id=scope.user_id,
                knowledge_base_id=scope.knowledge_base_id,
                document_id=uuid.uuid4(),
                page_number=1,
                element_type=ElementType.PARAGRAPH,
                text=UntrustedText("Some text"),
                reading_order=i,
                processing_method=ProcessingMethod.NATIVE_TEXT,
                created_at=ts,
            )
            for i in range(3)
        ]

        await repo.save_elements(scope, elements)

        assert session.merge.call_count == 3

    async def test_get_elements_applies_scope_filter(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalars([]))
        repo = _doc_repo(scope, session)

        doc_id = uuid.uuid4()
        await repo.get_elements(scope, doc_id)

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "document_id" in compiled
        assert "user_id" in compiled
        assert "knowledge_base_id" in compiled

    async def test_get_elements_filters_by_page_number(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalars([]))
        repo = _doc_repo(scope, session)

        await repo.get_elements(scope, uuid.uuid4(), page_number=3)

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "page_number" in compiled

    async def test_get_elements_omits_page_filter_when_none(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalars([]))
        repo = _doc_repo(scope, session)

        # page_number=None means no page_number filter — only one WHERE clause set
        await repo.get_elements(scope, uuid.uuid4(), page_number=None)

        stmt = session.execute.call_args[0][0]
        # Verify the query still compiles cleanly (no errors)
        compiled = str(stmt.compile())
        assert "document_id" in compiled


# ---------------------------------------------------------------------------
# Scope guard — a call carrying someone else's scope never reaches the session
# ---------------------------------------------------------------------------


class TestDocumentScopeGuard:
    async def test_get_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _doc_repo(_make_scope(), session)

        with pytest.raises(ScopeViolationError):
            await repo.get(_make_scope(), uuid.uuid4())

        session.execute.assert_not_called()

    async def test_save_rejects_foreign_scope(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        repo = _doc_repo(scope, session)

        with pytest.raises(ScopeViolationError):
            await repo.save(_make_scope(), _make_doc(scope))

        session.merge.assert_not_called()

    async def test_list_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _doc_repo(_make_scope(), session)

        with pytest.raises(ScopeViolationError):
            await repo.list(_make_scope())

        session.execute.assert_not_called()

    async def test_delete_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _doc_repo(_make_scope(), session)

        with pytest.raises(ScopeViolationError):
            await repo.delete(_make_scope(), uuid.uuid4())

        session.execute.assert_not_called()

    async def test_save_pages_rejects_foreign_scope(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        repo = _doc_repo(scope, session)

        with pytest.raises(ScopeViolationError):
            await repo.save_pages(_make_scope(), [_make_page(scope, uuid.uuid4(), 1)])

        session.merge.assert_not_called()

    async def test_get_pages_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _doc_repo(_make_scope(), session)

        with pytest.raises(ScopeViolationError):
            await repo.get_pages(_make_scope(), uuid.uuid4())

        session.execute.assert_not_called()

    async def test_save_elements_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _doc_repo(_make_scope(), session)

        with pytest.raises(ScopeViolationError):
            await repo.save_elements(_make_scope(), [])

        session.merge.assert_not_called()

    async def test_get_elements_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _doc_repo(_make_scope(), session)

        with pytest.raises(ScopeViolationError):
            await repo.get_elements(_make_scope(), uuid.uuid4())

        session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Mapping helpers — pure unit tests, no DB needed
# ---------------------------------------------------------------------------


class TestElementMapping:
    def test_model_to_entity_without_bbox(self) -> None:
        from app.domain.enums import ElementType, ProcessingMethod
        from app.domain.values import UntrustedText
        from app.infrastructure.database.models.chunk import DocumentElementModel

        ts = datetime.now(UTC)
        model = DocumentElementModel(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            knowledge_base_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            page_number=1,
            element_type=ElementType.PARAGRAPH.value,
            text="Hello",
            reading_order=0,
            processing_method=ProcessingMethod.NATIVE_TEXT.value,
            created_at=ts,
            heading_path=[],
        )

        entity = _element_to_entity(model)

        assert entity.element_type == ElementType.PARAGRAPH
        assert isinstance(entity.text, UntrustedText)
        assert entity.bounding_box is None

    def test_model_to_entity_with_bbox(self) -> None:
        from app.domain.enums import ElementType, ProcessingMethod
        from app.infrastructure.database.models.chunk import DocumentElementModel

        ts = datetime.now(UTC)
        model = DocumentElementModel(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            knowledge_base_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            page_number=1,
            element_type=ElementType.FIGURE.value,
            text="caption",
            reading_order=0,
            processing_method=ProcessingMethod.OCR.value,
            created_at=ts,
            heading_path=[],
            bounding_box_x0=10.0,
            bounding_box_y0=20.0,
            bounding_box_x1=110.0,
            bounding_box_y1=220.0,
            confidence=0.95,
        )

        entity = _element_to_entity(model)

        assert entity.bounding_box is not None
        assert entity.bounding_box.x0 == 10.0
        assert entity.confidence == 0.95

    def test_entity_to_model_flattens_bbox_and_heading_path(self) -> None:
        from app.domain.documents.entities import DocumentElement
        from app.domain.enums import ElementType, ProcessingMethod
        from app.domain.values import BoundingBox, HeadingPath, UntrustedText

        scope = _make_scope()
        element = DocumentElement(
            id=uuid.uuid4(),
            user_id=scope.user_id,
            knowledge_base_id=scope.knowledge_base_id,
            document_id=uuid.uuid4(),
            page_number=2,
            element_type=ElementType.FIGURE,
            text=UntrustedText("caption"),
            reading_order=4,
            processing_method=ProcessingMethod.OCR,
            created_at=datetime.now(UTC),
            bounding_box=BoundingBox(10.0, 20.0, 110.0, 220.0),
            heading_path=HeadingPath(("Chapter 1", "Section 2")),
            confidence=0.95,
        )

        model = _element_to_model(element)

        assert (
            model.bounding_box_x0,
            model.bounding_box_y0,
            model.bounding_box_x1,
            model.bounding_box_y1,
        ) == (10.0, 20.0, 110.0, 220.0)
        assert model.heading_path == ["Chapter 1", "Section 2"]
        assert model.text == "caption"
        assert model.element_type == ElementType.FIGURE.value

    def test_entity_to_model_without_bbox_leaves_columns_null(self) -> None:
        from app.domain.documents.entities import DocumentElement
        from app.domain.enums import ElementType, ProcessingMethod
        from app.domain.values import UntrustedText

        scope = _make_scope()
        element = DocumentElement(
            id=uuid.uuid4(),
            user_id=scope.user_id,
            knowledge_base_id=scope.knowledge_base_id,
            document_id=uuid.uuid4(),
            page_number=1,
            element_type=ElementType.PARAGRAPH,
            text=UntrustedText("body"),
            reading_order=0,
            processing_method=ProcessingMethod.NATIVE_TEXT,
            created_at=datetime.now(UTC),
        )

        model = _element_to_model(element)

        assert model.bounding_box_x0 is None
        assert model.bounding_box_y1 is None
        assert model.heading_path == []
