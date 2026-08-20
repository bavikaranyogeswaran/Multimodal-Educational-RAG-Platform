"""Evidence, citations, and the plan that decides how retrieval runs.

The chain this module exists to make unbreakable: retrieval produces evidence, evidence
carries a stable label, the model may cite only those labels, and validation resolves each
citation back through the same set that was actually put in front of the model. A citation
that names a real chunk which was never in context is a fabrication, and this is where that
becomes detectable rather than plausible.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Self
from uuid import UUID

from app.domain.documents.chunks import Chunk
from app.domain.enums import ChunkType, EarlyExitPath, ElementType, QueryClass, RetrieverKind
from app.domain.errors import InvariantViolationError, NotFoundError
from app.domain.invariants import require_non_negative, require_positive
from app.domain.models.generation import GeneratedAnswer
from app.domain.scope import ScopeContext
from app.domain.values import BoundingBox

_LABEL_PATTERN = re.compile(r"^S([1-9]\d*)$")


@dataclass(frozen=True, slots=True, order=True)
class EvidenceLabel:
    """The identifier the model uses to cite a source, rendered as `[S1]`.

    Deliberately short and positional. The model never sees a chunk identifier, so it
    cannot invent one that happens to exist — an invented label is either out of range or
    malformed, and both are caught.
    """

    number: int

    def __post_init__(self) -> None:
        require_positive(self.number, "EvidenceLabel.number")

    @classmethod
    def parse(cls, raw: str) -> Self:
        match = _LABEL_PATTERN.match(raw.strip().strip("[]"))
        if match is None:
            raise InvariantViolationError(f"{raw!r} is not a valid evidence label such as 'S1'")
        return cls(int(match.group(1)))

    @classmethod
    def try_parse(cls, raw: str) -> Self | None:
        """For parsing model output, where a malformed label is expected rather than fatal."""
        try:
            return cls.parse(raw)
        except InvariantViolationError:
            return None

    def __str__(self) -> str:
        return f"S{self.number}"

    @property
    def bracketed(self) -> str:
        return f"[S{self.number}]"


@dataclass(frozen=True, slots=True)
class Evidence:
    """A chunk selected for the prompt, with how it got there.

    Provenance is kept because it is what makes a retrieval decision explainable
    afterwards — which retrievers found this, where it ranked, what the reranker thought,
    and whether its parent had to be loaded to make it intelligible.
    """

    label: EvidenceLabel
    chunk: Chunk
    retrievers: frozenset[RetrieverKind]

    rank: int = 0
    rerank_score: float | None = None
    fusion_score: float | None = None
    parent_expanded: bool = False
    compressed: bool = False

    def __post_init__(self) -> None:
        require_non_negative(self.rank, "Evidence.rank")
        if not self.retrievers:
            raise InvariantViolationError(
                "Evidence must record at least one retriever — evidence that arrived from "
                "nowhere cannot be explained or reproduced"
            )

    @property
    def scope(self) -> ScopeContext:
        return self.chunk.scope

    @property
    def document_id(self) -> UUID:
        return self.chunk.document_id

    @property
    def token_count(self) -> int:
        return self.chunk.token_count

    @property
    def found_by_multiple_retrievers(self) -> bool:
        """Agreement between independent retrievers is a meaningful signal on its own."""
        return len(self.retrievers) > 1

    def to_citation(self, order: int) -> Citation:
        """The record persisted alongside an answer, so a claim stays traceable.

        `page_start` is the page cited even when the chunk spans several. A citation names
        where to begin reading, and the first page is the only one that answers that for
        every chunk; a range would have to be collapsed to a single page by whatever
        followed the link anyway.
        """
        return Citation(
            label=self.label,
            chunk_id=self.chunk.id,
            document_id=self.chunk.document_id,
            chunk_type=self.chunk.chunk_type,
            page_number=self.chunk.page_start,
            citation_order=order,
            element_type=self.chunk.element_type,
            bounding_box=self.chunk.bounding_box,
            evidence_hash=self.chunk.content_hash,
        )


@dataclass(frozen=True, slots=True)
class EvidenceSet:
    """Exactly the evidence that was put in front of the model.

    This is the authority for the question validation has to answer: *was this citation in
    context?* Nothing else can answer it, because nothing else knows what the prompt
    contained.

    Construction enforces that every item shares one scope. An evidence set spanning two
    Knowledge Bases would be a leak that had already happened by the time anyone looked,
    so it is refused at the point it would be assembled.
    """

    items: tuple[Evidence, ...]

    def __post_init__(self) -> None:
        if not self.items:
            return

        labels = [item.label for item in self.items]
        if len(set(labels)) != len(labels):
            raise InvariantViolationError("evidence labels must be unique within a set")

        scopes = {item.scope for item in self.items}
        if len(scopes) > 1:
            raise InvariantViolationError(
                "an EvidenceSet must not span more than one scope — mixed evidence would "
                "put another Knowledge Base's content in front of the model"
            )

    @classmethod
    def labelled(cls, chunks_with_provenance: list[Evidence]) -> Self:
        """Assign `S1`, `S2`, … in the order the evidence will appear in the prompt.

        Labels are positional, so they mean nothing outside the set that issued them.
        """
        relabelled = tuple(
            replace(item, label=EvidenceLabel(position))
            for position, item in enumerate(chunks_with_provenance, start=1)
        )
        return cls(relabelled)

    @classmethod
    def empty(cls) -> Self:
        return cls(())

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)

    @property
    def labels(self) -> tuple[EvidenceLabel, ...]:
        return tuple(item.label for item in self.items)

    @property
    def total_tokens(self) -> int:
        return sum(item.token_count for item in self.items)

    @property
    def scope(self) -> ScopeContext | None:
        """The single scope every item shares, or nothing when the set is empty."""
        return self.items[0].scope if self.items else None

    @property
    def document_ids(self) -> frozenset[UUID]:
        """Which documents contributed — how source coverage is measured."""
        return frozenset(item.document_id for item in self.items)

    def contains(self, label: EvidenceLabel) -> bool:
        return any(item.label == label for item in self.items)

    def find(self, label: EvidenceLabel) -> Evidence | None:
        return next((item for item in self.items if item.label == label), None)

    def require(self, label: EvidenceLabel) -> Evidence:
        """Resolve a cited label, refusing one that was never supplied.

        A model citing `S9` when five items were supplied has invented a source. It may
        even name a chunk that genuinely exists — which is precisely why the check is
        against this set rather than against the database.
        """
        found = self.find(label)
        if found is None:
            raise NotFoundError("evidence", f"{label} was not supplied to the model")
        return found


@dataclass(frozen=True, slots=True)
class Citation:
    """A persisted link from a claim back to the passage that carries it.

    Everything needed to take a reader to the source is here, because the evidence set that
    produced it does not outlive the turn. A label alone is positional and means nothing
    once the prompt is gone; these fields are what let a citation still be resolved a week
    later.

    `chunk_type` is carried alongside the location because where to look is not the same
    question as what to expect there. A citation into a table is followed differently from
    one into a paragraph — the reader is sent to a grid of numbers rather than to prose,
    and an interface that cannot tell them apart has to guess.

    `evidence_hash` records what the passage said at the moment it was cited. Chunks are
    rewritten when a document is reprocessed, and a citation whose hash no longer matches
    its chunk is pointing at text that has since changed — which is worth knowing, and
    undetectable without storing the hash at citation time.
    """

    label: EvidenceLabel
    chunk_id: UUID
    document_id: UUID
    chunk_type: ChunkType
    page_number: int
    citation_order: int

    element_type: ElementType | None = None
    bounding_box: BoundingBox | None = None
    evidence_hash: str | None = None

    def __post_init__(self) -> None:
        require_positive(self.page_number, "Citation.page_number")
        require_non_negative(self.citation_order, "Citation.citation_order")

    @property
    def is_navigable(self) -> bool:
        """Whether the interface can highlight the exact region, not merely open the page."""
        return self.bounding_box is not None


def resolve_citations(
    answer: GeneratedAnswer,
    evidence: Sequence[Evidence],
) -> tuple[Citation, ...]:
    """Turn a validated answer into the citation records that outlive the turn.

    One record per (claim, cited label) pair rather than per claim, because a claim resting
    on two passages is traceable to two places and collapsing them would lose one. The same
    passage cited by two different claims likewise produces two records — the question a
    reader asks is which passage supports *this* claim, not which passages the answer used
    somewhere.

    `citation_order` runs across the whole answer rather than restarting per claim, so the
    records sort back into the order the answer makes its case in. Claims keep the order the
    model emitted them; labels within a claim keep the order it cited them.

    Labels that resolve to nothing are skipped. A validated answer has none — the citation
    existence check rejects or repairs those long before this runs — but this function is
    what writes the permanent record, and a permanent record built on a label nobody could
    resolve would be worse than a shorter one.
    """
    by_label = {item.label: item for item in evidence}
    citations: list[Citation] = []

    for claim in answer.claims:
        for raw in claim.citations:
            label = EvidenceLabel.try_parse(raw)
            if label is None:
                continue
            found = by_label.get(label)
            if found is None:
                continue
            citations.append(found.to_citation(order=len(citations)))

    return tuple(citations)


@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    """Optional narrowing of a search.

    Only the optional filters live here. The mandatory ones — the user, the Knowledge Base,
    and the requirement that a document has finished processing — come from the scope and
    are not represented as fields, because a field can be left unset and these cannot.
    """

    document_ids: frozenset[UUID] = frozenset()
    chapter: str | None = None
    section: str | None = None
    page_number: int | None = None
    element_types: frozenset[ElementType] = frozenset()
    table_id: UUID | None = None
    figure_id: UUID | None = None
    language: str | None = None

    def __post_init__(self) -> None:
        if self.page_number is not None:
            require_positive(self.page_number, "RetrievalFilters.page_number")

    @property
    def is_narrowed(self) -> bool:
        return any(
            (
                self.document_ids,
                self.chapter,
                self.section,
                self.page_number is not None,
                self.element_types,
                self.table_id is not None,
                self.figure_id is not None,
                self.language,
            )
        )

    @property
    def targets_a_specific_object(self) -> bool:
        """A table or figure the student selected, rather than a region of the corpus."""
        return self.table_id is not None or self.figure_id is not None


@dataclass(frozen=True, slots=True)
class RetrievalPlan:
    """What the router decided, before any retrieval runs.

    Produced by rules over the query class, not by asking a model what it would like to
    do. Keeping it as a value means the decision can be logged, compared against the
    outcome, and tested without executing a search.
    """

    query_class: QueryClass
    retrievers: frozenset[RetrieverKind]
    expand_queries: bool
    consult_graph: bool
    decompose: bool

    #: Absent means the full pipeline runs. "No shortcut" is not a kind of shortcut, so
    #: it is represented by nothing rather than by a member standing for nothing.
    early_exit: EarlyExitPath | None = None
    filters: RetrievalFilters = field(default_factory=RetrievalFilters)

    def __post_init__(self) -> None:
        if not self.retrievers:
            raise InvariantViolationError("a RetrievalPlan must run at least one retriever")
        if self.consult_graph and RetrieverKind.GRAPH not in self.retrievers:
            raise InvariantViolationError(
                "consult_graph is set but the graph retriever is not in the plan"
            )
        if not self.consult_graph and RetrieverKind.GRAPH in self.retrievers:
            raise InvariantViolationError(
                "the graph retriever is in the plan but consult_graph is not set"
            )
        if self.early_exit is not None and self.expand_queries:
            raise InvariantViolationError(
                f"{self.early_exit} resolves the target already; expanding the query would "
                "add latency and candidates that cannot improve on it"
            )

    @classmethod
    def for_query(
        cls,
        query_class: QueryClass,
        *,
        filters: RetrievalFilters | None = None,
        graph_available: bool = False,
    ) -> Self:
        """Derive the plan from the classification.

        The routing rules live on the query class itself, so this reads as an application
        of them rather than as a second, separate set that could drift.
        """
        applied = filters or RetrievalFilters()

        early_exit = _EARLY_EXITS.get(query_class)
        # A shortcut is only a shortcut if the object it depends on was actually selected.
        # Asking about "the table on page 67" without having selected one still needs a
        # search to work out which table that is.
        needs_a_selection = {EarlyExitPath.TABLE_LOOKUP, EarlyExitPath.VISUAL_LOOKUP}
        if early_exit in needs_a_selection and not applied.targets_a_specific_object:
            early_exit = None

        retrievers = set(
            _BASE_RETRIEVERS.get(query_class, {RetrieverKind.DENSE, RetrieverKind.KEYWORD})
        )

        # Graph retrieval supplements the others; it never replaces them, and it only runs
        # when the Knowledge Base actually has a graph to traverse.
        consult_graph = graph_available and query_class.benefits_from_graph
        if consult_graph:
            retrievers.add(RetrieverKind.GRAPH)

        return cls(
            query_class=query_class,
            retrievers=frozenset(retrievers),
            expand_queries=not query_class.forbids_expansion and early_exit is None,
            consult_graph=consult_graph,
            decompose=query_class.needs_decomposition,
            early_exit=early_exit,
            filters=applied,
        )

    @property
    def runs_broad_retrieval(self) -> bool:
        return self.early_exit is None


_EARLY_EXITS: dict[QueryClass, EarlyExitPath] = {
    QueryClass.TABLE: EarlyExitPath.TABLE_LOOKUP,
    QueryClass.VISUAL: EarlyExitPath.VISUAL_LOOKUP,
    QueryClass.EXACT_TERM: EarlyExitPath.EXACT_LOOKUP,
}

_BASE_RETRIEVERS: dict[QueryClass, set[RetrieverKind]] = {
    QueryClass.TABLE: {RetrieverKind.TABLE, RetrieverKind.DENSE},
    QueryClass.VISUAL: {RetrieverKind.VISUAL, RetrieverKind.DENSE},
    # Exact quotations and identifiers are what keyword search is for; dense retrieval
    # stays in the plan because a paraphrase of the surrounding passage still helps.
    QueryClass.EXACT_TERM: {RetrieverKind.KEYWORD, RetrieverKind.DENSE},
}
