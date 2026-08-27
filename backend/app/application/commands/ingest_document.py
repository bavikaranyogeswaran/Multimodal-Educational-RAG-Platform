"""Use case: ingest a document that has already been uploaded and stored in R2.

Receives a Document entity that is already in PROCESSING state. Downloads the bytes from
object storage, parses them into pages and layout elements, persists both, splits the
elements into overlapping chunks, generates dense embeddings, and persists those. Returns
the document in COMPLETED state — the caller is responsible for saving it and committing.

Reading a document again replaces the earlier reading rather than joining it. Nothing
here is written under an identity a previous run would recognise, so without an explicit
sweep the two readings would sit side by side and retrieval would find both.

Pages and elements are written before chunking begins. They are what the parse actually
established, and they stay useful whether or not the stages after them succeed: a page
recorded as needing recognition is a fact worth keeping even if this run then fails.

Chunking works from the elements rather than from flattened page text, so the boundaries
it places are the document's own — a section ends, a paragraph ends — rather than a
character count arriving mid-word. Deciding where those boundaries go is a rule, and
lives in the domain; this use case supplies the elements and gives the results identities.

Chunking produces two tiers, and only the smaller one is embedded. The larger passages are
stored to be loaded once a search has already chosen something inside them, so putting them
in the index would mean a section and a paragraph within it competing over the same query.
"""

from __future__ import annotations

import hashlib
import json
import re as _re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog

from app.domain.documents.chunker import ChunkDraft, Chunker, ChunkFamily
from app.domain.documents.chunks import Chunk
from app.domain.documents.entities import Document, DocumentElement, ParsedPage
from app.domain.documents.figures import DocumentFigure, to_embedding_text
from app.domain.documents.table_render import render as render_table
from app.domain.documents.tables import DocumentTable
from app.domain.enums import ElementType, ModelTask
from app.domain.models.entities import ModelRequest
from app.domain.ports.adapters import EmbeddingPort, FigureCropperPort, PdfParserPort, StoragePort
from app.domain.ports.model_gateway import ModelGatewayPort
from app.domain.ports.repositories import ChunkRepository, DocumentRepository
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IngestDocumentCommand:
    scope: ScopeContext
    document: Document


class IngestDocumentUseCase:
    """Download → chunk → embed → persist.

    The caller (worker) is responsible for:
    - ensuring the document is in PROCESSING state before calling execute
    - saving the returned COMPLETED document
    - marking the job as COMPLETED
    - catching exceptions and transitioning both the document and job to FAILED
    """

    def __init__(
        self,
        chunk_repo: ChunkRepository,
        document_repo: DocumentRepository,
        storage: StoragePort,
        embedder: EmbeddingPort,
        *,
        parser: PdfParserPort,
        chunker: Chunker,
        embedding_model_id: str,
        index_version: int,
        figure_cropper: FigureCropperPort | None = None,
        crops_prefix: str = "figures",
        model_gateway: ModelGatewayPort | None = None,
    ) -> None:
        self._chunk_repo = chunk_repo
        self._document_repo = document_repo
        self._storage = storage
        self._embedder = embedder
        self._parser = parser
        self._chunker = chunker
        self._embedding_model_id = embedding_model_id
        self._index_version = index_version
        self._figure_cropper = figure_cropper
        self._crops_prefix = crops_prefix
        self._model_gateway = model_gateway

    async def execute(self, command: IngestDocumentCommand) -> Document:
        scope = command.scope
        doc = command.document
        now = datetime.now(UTC)

        # Download the original file from object storage
        data = await self._storage.get(doc.storage_key)

        # Parse into pages and layout elements. Pages whose text layer cannot be
        # trusted come back with no elements rather than with a partial reading.
        parsed = await self._parser.parse(data, document_id=doc.id, scope=scope)

        # Clear whatever an earlier reading of this document left behind, now that there
        # is a new reading to put in its place. Deliberately after the parse and not
        # before it: a parse that fails should leave the student with the copy they
        # already had rather than with nothing at all.
        await self._discard_previous_ingestion(scope, doc.id)

        # Persisted before chunking, because they are what the parse established and
        # they remain true regardless of what the later stages do.
        await self._document_repo.save_pages(scope, [item.page for item in parsed])
        elements = [element for item in parsed for element in item.elements]
        if elements:
            await self._document_repo.save_elements(scope, elements)

        # After the elements, never before: a table or figure names the element it was
        # read from, and that row has to exist for the reference to hold.
        tables = [_rendered(table) for item in parsed for table in item.tables]
        if tables:
            await self._document_repo.save_tables(scope, tables)

        figures = [figure for item in parsed for figure in item.figures]
        if figures:
            if self._figure_cropper is not None:
                figures = await _crop_and_upload_figures(
                    figures,
                    parsed,
                    data,
                    self._figure_cropper,
                    self._storage,
                    scope,
                    self._crops_prefix,
                )
            if self._model_gateway is not None:
                figures = await _describe_figures(figures, self._storage, self._model_gateway)
            await self._document_repo.save_figures(scope, figures)

        chunks = _to_chunks(
            self._chunker.chunk(
                _with_described_figures(_with_rendered_tables(elements, tables), figures)
            ),
            doc=doc,
            scope=scope,
            index_version=self._index_version,
            now=now,
            figure_by_element={fig.source_element_id: fig.id for fig in figures},
            table_by_element={tbl.source_element_id: tbl.id for tbl in tables},
        )

        if chunks:
            # Persist chunks (without embeddings) first so the DB row exists
            # before we write the embedding vector to it. Parents come before the
            # children naming them, so the reference is never to a row that is not
            # there yet.
            await self._chunk_repo.save_batch(scope, chunks)

            # Only children are embedded. A parent is what a match expands into, not
            # something to match against: embedding it would put a section and a
            # paragraph inside that section into the same ranking, competing for the
            # same slots and returning the same passage twice.
            searchable = [chunk for chunk in chunks if chunk.is_child]
            texts = [c.text.value for c in searchable]
            vectors = await self._embedder.embed_documents(texts)

            await self._chunk_repo.set_embeddings(
                scope,
                {c.id: v for c, v in zip(searchable, vectors, strict=True)},
                model_id=self._embedding_model_id,
                dimension=self._embedder.dimension,
                version=self._index_version,
            )

        # The parse counted the pages, so the count is known rather than inferred from
        # whichever page happened to yield text last.
        return doc.mark_completed(page_count=len(parsed), now=now)

    async def _discard_previous_ingestion(self, scope: ScopeContext, document_id: UUID) -> None:
        """Remove everything an earlier ingestion of this document produced.

        Reading the same file twice does not overwrite the first reading. Every page,
        element, table, figure and chunk is given a fresh identity on each run, so a
        second pass inserts a parallel copy alongside the first instead of replacing it.
        Both copies are then searchable, and retrieval starts returning one passage twice
        under two identities — the same text competing with itself for the slots an
        answer has to spend.

        The crops go before the figure rows that name them, because those rows hold the
        only record that the images exist. After they are gone the objects are still in
        the bucket with nothing left pointing at them, and no later run would know to
        look: a new reading mints new figure identities and so writes to new keys.

        A first ingestion reaches all of this too and finds nothing, which is the
        intended outcome rather than a case to guard against.
        """
        figures = await self._document_repo.get_figures(scope, document_id)
        await _discard_figure_crops(figures, self._storage)
        await self._chunk_repo.delete_for_document(scope, document_id)
        await self._document_repo.delete_parse(scope, document_id)


async def _discard_figure_crops(figures: Sequence[DocumentFigure], storage: StoragePort) -> None:
    """Delete the crop images a previous run uploaded.

    A delete that fails is logged and stepped over. The object it could not remove costs
    storage and nothing else — it is unreachable either way, since the row naming it is
    about to go. Failing the ingest over it would cost the student their document to
    save a file that is already garbage.
    """
    for figure in figures:
        if not figure.crop_key:
            continue
        try:
            await storage.delete(figure.crop_key)
        except Exception:
            _log.warning(
                "figure_crop_delete_failed",
                figure_id=str(figure.id),
                crop_key=figure.crop_key,
            )


# ---------------------------------------------------------------------------
# Figure crops
# ---------------------------------------------------------------------------


async def _crop_and_upload_figures(
    figures: Sequence[DocumentFigure],
    parsed: Sequence[ParsedPage],
    data: bytes,
    cropper: FigureCropperPort,
    storage: StoragePort,
    scope: ScopeContext,
    crops_prefix: str,
) -> list[DocumentFigure]:
    """Render each figure's bounding box, upload the crop, and return updated figures.

    A crop failure is logged and skipped rather than failing the whole ingest: a figure
    record without a crop_key is still valid and will be reattempted if ingestion re-runs.
    The page height needed for coordinate flipping is read from the ParsedPage that owns
    each figure.
    """
    page_heights: dict[int, float] = {item.page.page_number: item.page.height for item in parsed}

    result: list[DocumentFigure] = []
    for figure in figures:
        page_height = page_heights.get(figure.page_number)
        if page_height is None:
            result.append(figure)
            continue

        try:
            crop_bytes = await cropper.crop(
                data,
                page_number=figure.page_number,
                page_height=page_height,
                bounding_box=figure.bounding_box,
            )
        except Exception:
            _log.warning(
                "figure_crop_failed",
                figure_id=str(figure.id),
                page_number=figure.page_number,
            )
            result.append(figure)
            continue

        key = (
            f"{crops_prefix}/{scope.user_id}/{scope.knowledge_base_id}"
            f"/{figure.document_id}/{figure.id}.png"
        )
        await storage.put(key, crop_bytes, content_type="image/png")
        result.append(replace(figure, crop_key=key))

    return result


# ---------------------------------------------------------------------------
# Figure descriptions
# ---------------------------------------------------------------------------

_FIGURE_SYSTEM_PREAMBLE = (
    "You are an expert at analyzing figures, charts, and diagrams from educational documents. "
    "Your analysis is factual and concise. You output only valid JSON."
)

_FIGURE_TASK_INSTRUCTIONS = """\
Examine the image. Classify it as exactly one of:
  FIGURE   — a photograph, illustration, or image that is not a data chart or process diagram
  CHART    — any data visualization: bar chart, line graph, scatter plot, pie chart, histogram, etc.
  DIAGRAM  — a schematic, flowchart, architecture diagram, process flow, or structural illustration

Extract every readable text label visible in the image.
Write a 1–3 sentence factual description of what the image shows."""

_FIGURE_OUTPUT_SCHEMA = """\
Respond with exactly this JSON (no markdown fences, no extra text):
{
  "kind": "FIGURE | CHART | DIAGRAM",
  "description": "<factual 1-3 sentence description>",
  "ocr_text": "<all visible text labels, or null>",
  "chart_type": "<bar|line|scatter|pie|histogram|box|heatmap|area|other — CHART only, else null>",
  "x_axis_label": "<axis label text or null>",
  "y_axis_label": "<axis label text or null>",
  "units_label": "<units if visible or null>",
  "legend": "<legend items as comma-separated text or null>",
  "data_labels": "<data-point annotations if visible or null>",
  "visible_trend": "<one sentence describing the trend — CHART only, else null>",
  "diagram_labels": ["<label1>", "<label2>"],
  "components": ["<component1>", "<component2>"],
  "arrows": ["<A -> B>", "<C -> D>"],
  "visible_relationships": ["<relationship>"]
}
Rules:
  FIGURE  — chart fields null, diagram arrays empty
  CHART   — populate chart fields, diagram arrays empty
  DIAGRAM — chart fields null, populate diagram arrays"""

_FIGURE_QUERY = "Analyze this image and return the JSON as specified."

# Map from model response string to the domain enum value.
_KIND_MAP: dict[str, ElementType] = {
    "FIGURE": ElementType.FIGURE,
    "CHART": ElementType.CHART,
    "DIAGRAM": ElementType.DIAGRAM,
}


async def _describe_figures(
    figures: Sequence[DocumentFigure],
    storage: StoragePort,
    model_gateway: ModelGatewayPort,
) -> list[DocumentFigure]:
    """Call the vision model on each figure crop and return updated figures.

    Only figures that already have a crop_key are sent to the model; the rest
    pass through unchanged. A failure on any individual figure is logged and
    skipped — the figure record is kept without a description rather than
    losing it entirely.
    """
    request = ModelRequest(
        model_task=ModelTask.VISUAL_QUESTION,
        system_preamble=_FIGURE_SYSTEM_PREAMBLE,
        safety_rules=(),
        task_instructions=_FIGURE_TASK_INSTRUCTIONS,
        query=_FIGURE_QUERY,
        output_schema=_FIGURE_OUTPUT_SCHEMA,
    )

    result: list[DocumentFigure] = []
    for figure in figures:
        if not figure.crop_key:
            result.append(figure)
            continue

        try:
            image_bytes = await storage.get(figure.crop_key)
            response = await model_gateway.generate_with_image(request, image_bytes)
            updates = _parse_vision_response(response.content.value)
            result.append(replace(figure, **updates) if updates else figure)
        except Exception:
            _log.warning(
                "figure_description_failed",
                figure_id=str(figure.id),
                page_number=figure.page_number,
            )
            result.append(figure)

    return result


def _parse_vision_response(text: str) -> dict[str, object]:
    """Extract structured fields from a model response.

    Returns a dict suitable for `replace(figure, ...)`. Returns an empty dict
    if the response is unparseable, leaving the figure unchanged.
    """
    try:
        data = json.loads(text)
    except ValueError:
        # The model sometimes wraps JSON in markdown fences or adds commentary.
        match = _re.search(r"\{.*\}", text, _re.DOTALL)
        if not match:
            return {}
        try:
            data = json.loads(match.group())
        except ValueError:
            return {}

    updates: dict[str, object] = {}

    kind = _KIND_MAP.get(str(data.get("kind", "")))
    if kind is not None:
        updates["kind"] = kind

    for field in (
        "description",
        "ocr_text",
        "chart_type",
        "x_axis_label",
        "y_axis_label",
        "units_label",
        "legend",
        "data_labels",
        "visible_trend",
    ):
        val = data.get(field)
        if val is not None:
            updates[field] = str(val) or None

    for field in ("diagram_labels", "components", "arrows", "visible_relationships"):
        val = data.get(field)
        if isinstance(val, list):
            updates[field] = tuple(str(item) for item in val if item)

    return updates


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _rendered(table: DocumentTable) -> DocumentTable:
    """Attach every serialised form to a table before it is stored."""
    rendering = render_table(table)
    return table.with_renderings(
        # `ensure_ascii=False` because the cells are real document text and may hold
        # accented characters, superscripts or symbols. Escaping them would store a
        # different string from the one that was read.
        table_json=json.dumps(rendering.table_json, ensure_ascii=False),
        markdown=rendering.markdown,
        html=rendering.html,
        embedding_text=rendering.embedding_text,
    )


def _with_rendered_tables(
    elements: Sequence[DocumentElement],
    tables: Sequence[DocumentTable],
) -> list[DocumentElement]:
    """Swap each table element's joined cells for the prose the table renders to.

    Only the copy handed to the chunker changes; the stored element keeps the literal
    reading of the page. The two are wanted for different things — the element records
    what the region says, and what gets embedded should be the form a question can
    actually match, where every row names its own columns instead of relying on a header
    line that a chunk boundary may have left behind.
    """
    prose = {
        table.source_element_id: table.embedding_text
        for table in tables
        if table.embedding_text
    }
    return [
        replace(element, text=UntrustedText(prose[element.id]))
        if element.id in prose
        else element
        for element in elements
    ]


def _with_described_figures(
    elements: Sequence[DocumentElement],
    figures: Sequence[DocumentFigure],
) -> list[DocumentElement]:
    """Give each figure element the prose its figure record renders to.

    A figure region is parsed with no text at all — the caption and everything the vision
    model read live on the figure record, one table away from the elements the chunker
    sees. Without this the chunker is handed an empty element, produces nothing for it,
    and every figure in the document ends up unreachable no matter how well it was read.

    Runs after the figures are described, so the text carries the description rather than
    just the caption. As with tables, only the copy handed to the chunker changes; the
    stored element still records what the region literally was.
    """
    prose: dict[UUID, str] = {}
    for figure in figures:
        rendered = to_embedding_text(figure)
        if rendered:
            prose[figure.source_element_id] = rendered
    return [
        replace(element, text=UntrustedText(prose[element.id]))
        if element.id in prose
        else element
        for element in elements
    ]


def _to_chunks(
    families: Sequence[ChunkFamily],
    *,
    doc: Document,
    scope: ScopeContext,
    index_version: int,
    now: datetime,
    figure_by_element: dict[UUID, UUID] | None = None,
    table_by_element: dict[UUID, UUID] | None = None,
) -> list[Chunk]:
    """Give each decided chunk an identity and the attributes storage needs.

    The chunker settled what the chunks are. Everything added here — an id, a position
    in the document, which index version produced it — is about keeping them rather than
    about the document they came from.

    The linkage is why identities are handed out here rather than in the chunker: a child
    can only name its parent once the parent has an id, and ids belong to whoever stores
    the rows. Each parent is emitted immediately before the children that name it, so the
    list can be written in order without a second pass.

    The two tiers are numbered separately. An ordinal says where a chunk sits among the
    chunks like it, and a single sequence across both would mean the chunk after child
    seven is sometimes a parent — which would make the neighbours of a passage depend on
    how the section above it happened to be divided.
    """
    chunks: list[Chunk] = []
    child_ordinal = 0
    fig_map = figure_by_element or {}
    tbl_map = table_by_element or {}

    for parent_ordinal, family in enumerate(families):
        parent = _chunk_from(
            family.parent,
            ordinal=parent_ordinal,
            parent_chunk_id=None,
            doc=doc,
            scope=scope,
            index_version=index_version,
            now=now,
            figure_id=fig_map.get(family.parent.source_element_id) if family.parent.source_element_id else None,
            table_id=tbl_map.get(family.parent.source_element_id) if family.parent.source_element_id else None,
        )
        chunks.append(parent)

        for draft in family.children:
            chunks.append(
                _chunk_from(
                    draft,
                    ordinal=child_ordinal,
                    parent_chunk_id=parent.id,
                    doc=doc,
                    scope=scope,
                    index_version=index_version,
                    now=now,
                    figure_id=fig_map.get(draft.source_element_id) if draft.source_element_id else None,
                    table_id=tbl_map.get(draft.source_element_id) if draft.source_element_id else None,
                )
            )
            child_ordinal += 1

    return chunks


def _chunk_from(
    draft: ChunkDraft,
    *,
    ordinal: int,
    parent_chunk_id: UUID | None,
    doc: Document,
    scope: ScopeContext,
    index_version: int,
    now: datetime,
    figure_id: UUID | None = None,
    table_id: UUID | None = None,
) -> Chunk:
    return Chunk(
        id=uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        document_id=doc.id,
        parent_chunk_id=parent_chunk_id,
        source_element_id=draft.source_element_id,
        figure_id=figure_id,
        table_id=table_id,
        chunk_type=draft.chunk_type,
        text=UntrustedText(draft.text),
        token_count=draft.token_count,
        ordinal=ordinal,
        page_start=draft.page_start,
        page_end=draft.page_end,
        index_version=index_version,
        created_at=now,
        language=doc.language,
        content_hash=hashlib.sha256(draft.text.encode()).hexdigest(),
        heading_path=draft.heading_path,
        chapter=draft.chapter,
        section=draft.section,
        element_type=draft.element_type,
        bounding_box=draft.bounding_box,
    )
