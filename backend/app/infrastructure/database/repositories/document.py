"""SQLAlchemy implementation of DocumentRepository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from app.domain.documents.entities import Document, DocumentElement, DocumentPage
from app.domain.documents.figures import DocumentFigure
from app.domain.documents.tables import DocumentTable
from app.domain.enums import DocumentStatus, ElementType, PageKind, ProcessingMethod
from app.domain.scope import ScopeContext
from app.domain.values import BoundingBox, HeadingPath, UntrustedText
from app.infrastructure.database.models.chunk import DocumentElementModel
from app.infrastructure.database.models.document import DocumentModel, DocumentPageModel
from app.infrastructure.database.models.figure import DocumentFigureModel
from app.infrastructure.database.models.table import DocumentTableModel
from app.infrastructure.database.repository import ScopedRepository


class SqlDocumentRepository(ScopedRepository):
    """Reads and writes Document, DocumentPage, DocumentElement, DocumentTable and DocumentFigure."""

    async def get(self, scope: ScopeContext, document_id: UUID) -> Document | None:
        self._require_scope(scope)
        stmt = (
            select(DocumentModel)
            .where(
                DocumentModel.id == document_id,
                self._scope_filter(DocumentModel),
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _doc_to_entity(row) if row else None

    async def save(self, scope: ScopeContext, document: Document) -> None:
        self._require_scope(scope)
        await self._session.merge(_doc_to_model(document))

    async def list(self, scope: ScopeContext) -> Sequence[Document]:
        self._require_scope(scope)
        stmt = (
            select(DocumentModel)
            .where(self._scope_filter(DocumentModel))
            .order_by(DocumentModel.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_doc_to_entity(row) for row in rows]

    async def delete(self, scope: ScopeContext, document_id: UUID) -> None:
        self._require_scope(scope)
        stmt = sa_delete(DocumentModel).where(
            DocumentModel.id == document_id,
            self._scope_filter(DocumentModel),
        )
        await self._session.execute(stmt)

    async def save_pages(
        self, scope: ScopeContext, pages: Sequence[DocumentPage]
    ) -> None:
        self._require_scope(scope)
        for page in pages:
            await self._session.merge(_page_to_model(page))

    async def get_pages(
        self, scope: ScopeContext, document_id: UUID
    ) -> Sequence[DocumentPage]:
        self._require_scope(scope)
        stmt = (
            select(DocumentPageModel)
            .where(
                DocumentPageModel.document_id == document_id,
                self._scope_filter(DocumentPageModel),
            )
            .order_by(DocumentPageModel.page_number.asc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_page_to_entity(row) for row in rows]

    async def save_elements(
        self, scope: ScopeContext, elements: Sequence[DocumentElement]
    ) -> None:
        self._require_scope(scope)
        for element in elements:
            await self._session.merge(_element_to_model(element))

    async def get_elements(
        self,
        scope: ScopeContext,
        document_id: UUID,
        *,
        page_number: int | None = None,
    ) -> Sequence[DocumentElement]:
        self._require_scope(scope)
        stmt = (
            select(DocumentElementModel)
            .where(
                DocumentElementModel.document_id == document_id,
                self._scope_filter(DocumentElementModel),
            )
            .order_by(
                DocumentElementModel.page_number.asc(),
                DocumentElementModel.reading_order.asc(),
            )
        )
        if page_number is not None:
            stmt = stmt.where(DocumentElementModel.page_number == page_number)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_element_to_entity(row) for row in rows]

    async def save_tables(self, scope: ScopeContext, tables: Sequence[DocumentTable]) -> None:
        self._require_scope(scope)
        for table in tables:
            await self._session.merge(_table_to_model(table))

    async def get_tables(
        self,
        scope: ScopeContext,
        document_id: UUID,
        *,
        page_number: int | None = None,
    ) -> Sequence[DocumentTable]:
        self._require_scope(scope)
        stmt = (
            select(DocumentTableModel)
            .where(
                DocumentTableModel.document_id == document_id,
                self._scope_filter(DocumentTableModel),
            )
            .order_by(DocumentTableModel.page_number.asc())
        )
        if page_number is not None:
            stmt = stmt.where(DocumentTableModel.page_number == page_number)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_table_to_entity(row) for row in rows]

    async def save_figures(self, scope: ScopeContext, figures: Sequence[DocumentFigure]) -> None:
        self._require_scope(scope)
        for figure in figures:
            await self._session.merge(_figure_to_model(figure))

    async def get_figures(
        self,
        scope: ScopeContext,
        document_id: UUID,
        *,
        page_number: int | None = None,
    ) -> Sequence[DocumentFigure]:
        self._require_scope(scope)
        stmt = (
            select(DocumentFigureModel)
            .where(
                DocumentFigureModel.document_id == document_id,
                self._scope_filter(DocumentFigureModel),
            )
            .order_by(DocumentFigureModel.page_number.asc())
        )
        if page_number is not None:
            stmt = stmt.where(DocumentFigureModel.page_number == page_number)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_figure_to_entity(row) for row in rows]

    async def delete_parse(self, scope: ScopeContext, document_id: UUID) -> None:
        self._require_scope(scope)
        # Figures and tables first: each one names the element it was read from, so
        # they go before the elements do. Every one of these tables cascades from the
        # document anyway, but nothing here is deleting the document — and naming each
        # table keeps what a re-reading clears readable in this method, rather than
        # inferred from foreign keys declared in four other files.
        await self._delete_document_rows(DocumentFigureModel, document_id)
        await self._delete_document_rows(DocumentTableModel, document_id)
        await self._delete_document_rows(DocumentElementModel, document_id)
        await self._delete_document_rows(DocumentPageModel, document_id)

    async def delete_page_elements(
        self, scope: ScopeContext, document_id: UUID, page_number: int
    ) -> None:
        self._require_scope(scope)
        await self._session.execute(
            sa_delete(DocumentElementModel).where(
                DocumentElementModel.document_id == document_id,
                DocumentElementModel.page_number == page_number,
                self._scope_filter(DocumentElementModel),
            )
        )

    async def _delete_document_rows(self, model: type[Any], document_id: UUID) -> None:
        """Delete one table's rows for one document, within the bound scope."""
        await self._session.execute(
            sa_delete(model).where(
                model.document_id == document_id,
                self._scope_filter(model),
            )
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _utc(dt: datetime) -> datetime:
    """Return dt unchanged if timezone-aware; attach UTC when SQLite strips it."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _utc_opt(dt: datetime | None) -> datetime | None:
    return None if dt is None else _utc(dt)


# ---------------------------------------------------------------------------
# Document mapping
# ---------------------------------------------------------------------------


def _doc_to_entity(row: DocumentModel) -> Document:
    return Document(
        id=row.id,
        user_id=row.user_id,
        knowledge_base_id=row.knowledge_base_id,
        filename=row.filename,
        content_type=row.content_type,
        byte_size=row.byte_size,
        storage_key=row.storage_key,
        status=DocumentStatus(row.status),
        title=row.title,
        page_count=row.page_count,
        checksum=row.checksum,
        language=row.language,
        failure_reason=row.failure_reason,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
        processed_at=_utc_opt(row.processed_at),
    )


def _doc_to_model(doc: Document) -> DocumentModel:
    return DocumentModel(
        id=doc.id,
        user_id=doc.user_id,
        knowledge_base_id=doc.knowledge_base_id,
        filename=doc.filename,
        content_type=doc.content_type,
        byte_size=doc.byte_size,
        storage_key=doc.storage_key,
        status=doc.status.value,
        title=doc.title,
        page_count=doc.page_count,
        checksum=doc.checksum,
        language=doc.language,
        failure_reason=doc.failure_reason,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        processed_at=doc.processed_at,
    )


# ---------------------------------------------------------------------------
# DocumentPage mapping
# ---------------------------------------------------------------------------


def _page_to_entity(row: DocumentPageModel) -> DocumentPage:
    return DocumentPage(
        id=row.id,
        user_id=row.user_id,
        knowledge_base_id=row.knowledge_base_id,
        document_id=row.document_id,
        page_number=row.page_number,
        kind=PageKind(row.kind),
        width=row.width,
        height=row.height,
        rotation=row.rotation,
        ocr_confidence=row.ocr_confidence,
        processed_at=_utc_opt(row.processed_at),
    )


def _page_to_model(page: DocumentPage) -> DocumentPageModel:
    return DocumentPageModel(
        id=page.id,
        user_id=page.user_id,
        knowledge_base_id=page.knowledge_base_id,
        document_id=page.document_id,
        page_number=page.page_number,
        kind=page.kind.value,
        width=page.width,
        height=page.height,
        rotation=page.rotation,
        ocr_confidence=page.ocr_confidence,
        processed_at=page.processed_at,
    )


# ---------------------------------------------------------------------------
# DocumentElement mapping
# ---------------------------------------------------------------------------


def _element_to_entity(row: DocumentElementModel) -> DocumentElement:
    bbox = None
    if row.bounding_box_x0 is not None:
        bbox = BoundingBox(
            x0=row.bounding_box_x0,
            y0=row.bounding_box_y0,  # type: ignore[arg-type]
            x1=row.bounding_box_x1,  # type: ignore[arg-type]
            y1=row.bounding_box_y1,  # type: ignore[arg-type]
        )
    raw_path = row.heading_path
    segments: tuple[str, ...] = tuple(raw_path) if raw_path else ()
    return DocumentElement(
        id=row.id,
        user_id=row.user_id,
        knowledge_base_id=row.knowledge_base_id,
        document_id=row.document_id,
        page_number=row.page_number,
        element_type=ElementType(row.element_type),
        text=UntrustedText(row.text),
        reading_order=row.reading_order,
        processing_method=ProcessingMethod(row.processing_method),
        created_at=_utc(row.created_at),
        bounding_box=bbox,
        heading_path=HeadingPath(segments),
        confidence=row.confidence,
    )


def _element_to_model(element: DocumentElement) -> DocumentElementModel:
    bbox = element.bounding_box
    return DocumentElementModel(
        id=element.id,
        user_id=element.user_id,
        knowledge_base_id=element.knowledge_base_id,
        document_id=element.document_id,
        page_number=element.page_number,
        element_type=element.element_type.value,
        text=element.text.value,
        reading_order=element.reading_order,
        processing_method=element.processing_method.value,
        created_at=element.created_at,
        bounding_box_x0=bbox.x0 if bbox else None,
        bounding_box_y0=bbox.y0 if bbox else None,
        bounding_box_x1=bbox.x1 if bbox else None,
        bounding_box_y1=bbox.y1 if bbox else None,
        heading_path=list(element.heading_path.segments),
        confidence=element.confidence,
    )


def _table_to_model(table: DocumentTable) -> DocumentTableModel:
    box = table.bounding_box
    return DocumentTableModel(
        id=table.id,
        user_id=table.user_id,
        knowledge_base_id=table.knowledge_base_id,
        document_id=table.document_id,
        source_element_id=table.source_element_id,
        page_number=table.page_number,
        headers=list(table.headers),
        # Stored as None rather than an empty array when no column carries a unit, so
        # "nothing was measured" and "units were never looked for" stay distinguishable.
        units=list(table.units) if table.units else None,
        rows=[list(row) for row in table.rows],
        caption=table.caption.value if table.caption is not None else None,
        number=table.number,
        bounding_box_x0=box.x0,
        bounding_box_y0=box.y0,
        bounding_box_x1=box.x1,
        bounding_box_y1=box.y1,
        confidence=table.confidence,
        created_at=table.created_at,
        table_json=table.table_json,
        markdown=table.markdown,
        html=table.html,
        embedding_text=table.embedding_text,
    )


def _table_to_entity(row: DocumentTableModel) -> DocumentTable:
    return DocumentTable(
        id=row.id,
        user_id=row.user_id,
        knowledge_base_id=row.knowledge_base_id,
        document_id=row.document_id,
        source_element_id=row.source_element_id,
        page_number=row.page_number,
        headers=tuple(row.headers),
        units=tuple(row.units) if row.units else (),
        rows=tuple(tuple(cells) for cells in row.rows),
        caption=UntrustedText(row.caption) if row.caption is not None else None,
        number=row.number,
        bounding_box=BoundingBox(
            x0=row.bounding_box_x0,
            y0=row.bounding_box_y0,
            x1=row.bounding_box_x1,
            y1=row.bounding_box_y1,
        ),
        confidence=row.confidence,
        created_at=_utc(row.created_at),
        table_json=row.table_json,
        markdown=row.markdown,
        html=row.html,
        embedding_text=row.embedding_text,
    )


# ---------------------------------------------------------------------------
# DocumentFigure mapping
# ---------------------------------------------------------------------------


def _figure_to_model(figure: DocumentFigure) -> DocumentFigureModel:
    box = figure.bounding_box
    return DocumentFigureModel(
        id=figure.id,
        user_id=figure.user_id,
        knowledge_base_id=figure.knowledge_base_id,
        document_id=figure.document_id,
        source_element_id=figure.source_element_id,
        page_number=figure.page_number,
        kind=figure.kind.value,
        bounding_box_x0=box.x0,
        bounding_box_y0=box.y0,
        bounding_box_x1=box.x1,
        bounding_box_y1=box.y1,
        caption=figure.caption.value if figure.caption is not None else None,
        number=figure.number,
        confidence=figure.confidence,
        created_at=figure.created_at,
        crop_key=figure.crop_key,
        ocr_text=figure.ocr_text,
        surrounding_text=figure.surrounding_text,
        description=figure.description,
        title=figure.title,
        chart_type=figure.chart_type,
        x_axis_label=figure.x_axis_label,
        y_axis_label=figure.y_axis_label,
        units_label=figure.units_label,
        legend=figure.legend,
        data_labels=figure.data_labels,
        visible_trend=figure.visible_trend,
        diagram_labels=list(figure.diagram_labels) if figure.diagram_labels else None,
        components=list(figure.components) if figure.components else None,
        arrows=list(figure.arrows) if figure.arrows else None,
        visible_relationships=(
            list(figure.visible_relationships) if figure.visible_relationships else None
        ),
    )


def _figure_to_entity(row: DocumentFigureModel) -> DocumentFigure:
    return DocumentFigure(
        id=row.id,
        user_id=row.user_id,
        knowledge_base_id=row.knowledge_base_id,
        document_id=row.document_id,
        source_element_id=row.source_element_id,
        page_number=row.page_number,
        kind=ElementType(row.kind),
        bounding_box=BoundingBox(
            x0=row.bounding_box_x0,
            y0=row.bounding_box_y0,
            x1=row.bounding_box_x1,
            y1=row.bounding_box_y1,
        ),
        caption=UntrustedText(row.caption) if row.caption is not None else None,
        number=row.number,
        confidence=row.confidence,
        created_at=_utc(row.created_at),
        crop_key=row.crop_key,
        ocr_text=row.ocr_text,
        surrounding_text=row.surrounding_text,
        description=row.description,
        title=row.title,
        chart_type=row.chart_type,
        x_axis_label=row.x_axis_label,
        y_axis_label=row.y_axis_label,
        units_label=row.units_label,
        legend=row.legend,
        data_labels=row.data_labels,
        visible_trend=row.visible_trend,
        diagram_labels=tuple(row.diagram_labels) if row.diagram_labels else (),
        components=tuple(row.components) if row.components else (),
        arrows=tuple(row.arrows) if row.arrows else (),
        visible_relationships=tuple(row.visible_relationships) if row.visible_relationships else (),
    )
