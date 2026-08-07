"""The closed sets of values the domain reasons about.

`StrEnum` throughout, so a member compares equal to its own string and stores and
serialises as itself — there is no separate mapping to keep in step. The two ordered
enums are `IntEnum`, because their ordering is the whole point rather than an accident of
declaration.

Nothing here imports anything but the standard library.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import IntEnum, StrEnum
from typing import Final


# ---------------------------------------------------------------------------
# Documents and ingestion
# ---------------------------------------------------------------------------
class PageKind(StrEnum):
    """How a page must be read, decided before any extraction happens.

    The distinction matters because the heavier vision-language model is expensive and
    must run on a small minority of pages, not on everything.
    """

    NATIVE_TEXT = "NATIVE_TEXT"
    SCANNED = "SCANNED"
    MIXED = "MIXED"
    COMPLEX = "COMPLEX"


class ProcessingMethod(StrEnum):
    """How a particular element's text was actually obtained.

    Recorded per element rather than per page: a mixed page yields some elements from the
    text layer and others from OCR, and knowing which is which is what lets a low
    confidence be attributed to the right cause.
    """

    NATIVE_TEXT = "NATIVE_TEXT"
    OCR = "OCR"
    OCR_VL = "OCR_VL"
    TABLE_EXTRACTION = "TABLE_EXTRACTION"


class ElementType(StrEnum):
    """Structural elements produced by layout-aware parsing.

    The parser emits these rather than flattened text, so table rows cannot mix with
    paragraphs and a caption cannot drift away from its figure.
    """

    HEADING = "HEADING"
    PARAGRAPH = "PARAGRAPH"
    LIST = "LIST"
    TABLE = "TABLE"
    FIGURE = "FIGURE"
    CHART = "CHART"
    DIAGRAM = "DIAGRAM"
    FORMULA = "FORMULA"
    CAPTION = "CAPTION"


class ChunkType(StrEnum):
    """What a retrievable chunk contains.

    Modalities stay separate but linked, so a table is retrievable as a table rather than
    as prose that happens to mention numbers.
    """

    TEXT = "TEXT"
    TABLE = "TABLE"
    FIGURE = "FIGURE"
    CHART = "CHART"
    DIAGRAM = "DIAGRAM"
    FORMULA = "FORMULA"
    DEFINITION = "DEFINITION"
    EXAMPLE = "EXAMPLE"


class DocumentStatus(StrEnum):
    """Lifecycle of an uploaded document.

    Only `COMPLETED` is retrievable. `DELETING` blocks retrieval immediately, before the
    deletion job has removed anything.
    """

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DELETING = "DELETING"

    @property
    def is_retrievable(self) -> bool:
        return self is DocumentStatus.COMPLETED

    @property
    def is_terminal(self) -> bool:
        return self in {DocumentStatus.COMPLETED, DocumentStatus.FAILED}

    def can_transition_to(self, target: DocumentStatus) -> bool:
        return target in _DOCUMENT_TRANSITIONS[self]

    @property
    def successors(self) -> frozenset[DocumentStatus]:
        return _DOCUMENT_TRANSITIONS[self]


_DOCUMENT_TRANSITIONS: Final[Mapping[DocumentStatus, frozenset[DocumentStatus]]] = {
    DocumentStatus.PENDING: frozenset(
        {DocumentStatus.PROCESSING, DocumentStatus.FAILED, DocumentStatus.DELETING}
    ),
    DocumentStatus.PROCESSING: frozenset(
        {DocumentStatus.COMPLETED, DocumentStatus.FAILED, DocumentStatus.DELETING}
    ),
    # Reprocessing an indexed document goes straight back to processing. Returning it to
    # pending would be a lie: the work is already queued, and the document would appear
    # never to have been ingested.
    DocumentStatus.COMPLETED: frozenset({DocumentStatus.PROCESSING, DocumentStatus.DELETING}),
    DocumentStatus.FAILED: frozenset(
        {DocumentStatus.PENDING, DocumentStatus.PROCESSING, DocumentStatus.DELETING}
    ),
    # Absorbing. Once deletion begins there is no way back — retrieval is blocked from
    # that moment, and a document that could return from deleting would be retrievable
    # again after its files had gone.
    DocumentStatus.DELETING: frozenset(),
}


class ExplanationLevel(StrEnum):
    """How much prior knowledge an explanation may assume.

    A property of the Knowledge Base rather than of a request: a student studying for a
    first-year course wants the same register every time, not one they must restate.
    """

    INTRODUCTORY = "INTRODUCTORY"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"


# ---------------------------------------------------------------------------
# Background jobs
# ---------------------------------------------------------------------------
class JobType(StrEnum):
    SYNC_GRAPH_PROJECTION = "SYNC_NEO4J"
    """Retained under its original name for schema compatibility.

    Currently a no-op: the graph is canonical in PostgreSQL and has no separate
    projection to synchronise. The job type exists so introducing one later does not
    require a migration.
    """

    DOCUMENT_INGESTION = "DOCUMENT_INGESTION"
    OCR_PAGE = "OCR_PAGE"
    GENERATE_EMBEDDINGS = "GENERATE_EMBEDDINGS"
    BUILD_GRAPH = "BUILD_GRAPH"
    COMPACT_MEMORY = "COMPACT_MEMORY"
    REBUILD_SUMMARY = "REBUILD_SUMMARY"
    DELETE_DOCUMENT = "DELETE_DOCUMENT"
    DELETE_KNOWLEDGE_BASE = "DELETE_KNOWLEDGE_BASE"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            JobStatus.COMPLETED,
            JobStatus.DEAD_LETTER,
            JobStatus.CANCELLED,
        }

    def can_transition_to(self, target: JobStatus) -> bool:
        return target in _JOB_TRANSITIONS[self]

    @property
    def successors(self) -> frozenset[JobStatus]:
        return _JOB_TRANSITIONS[self]


_JOB_TRANSITIONS: Final[Mapping[JobStatus, frozenset[JobStatus]]] = {
    JobStatus.PENDING: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.RUNNING: frozenset(
        {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.DEAD_LETTER, JobStatus.CANCELLED}
    ),
    # A failed job can be requeued (if attempts remain) or cancelled.
    JobStatus.FAILED: frozenset({JobStatus.PENDING, JobStatus.CANCELLED}),
    # An admin action can cancel a dead-lettered job; it can never be retried.
    JobStatus.DEAD_LETTER: frozenset({JobStatus.CANCELLED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


class JobPriority(IntEnum):
    """Claim order for the queue.

    Numeric because workers claim by descending priority, and an ordering that has to be
    reconstructed from a lookup table is one that will eventually be reconstructed wrong.
    Interactive work outranks ingestion, graph building and bulk compaction.
    """

    BACKGROUND = 10
    NORMAL = 20
    INTERACTIVE = 30


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------
class MessageRole(StrEnum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class MessageStatus(StrEnum):
    """A user message is persisted before generation begins, so it needs a status of its
    own — a failed generation must not lose the question that prompted it."""

    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in {MessageStatus.COMPLETED, MessageStatus.FAILED}

    def can_transition_to(self, target: MessageStatus) -> bool:
        return target in _MESSAGE_TRANSITIONS[self]

    @property
    def successors(self) -> frozenset[MessageStatus]:
        return _MESSAGE_TRANSITIONS[self]


_MESSAGE_TRANSITIONS: Final[Mapping[MessageStatus, frozenset[MessageStatus]]] = {
    MessageStatus.RECEIVED: frozenset({MessageStatus.PROCESSING}),
    MessageStatus.PROCESSING: frozenset({MessageStatus.COMPLETED, MessageStatus.FAILED}),
    # Generation completed or failed — both are absorbing.
    MessageStatus.COMPLETED: frozenset(),
    MessageStatus.FAILED: frozenset(),
}


# ---------------------------------------------------------------------------
# Query routing and retrieval
# ---------------------------------------------------------------------------
class QueryClass(StrEnum):
    """Deterministic router output. Rule-based classification, not a model decision."""

    DIRECT = "DIRECT"
    EXACT_TERM = "EXACT_TERM"
    TABLE = "TABLE"
    VISUAL = "VISUAL"
    RELATIONSHIP = "RELATIONSHIP"
    PREREQUISITE = "PREREQUISITE"
    CONCEPT_MAP = "CONCEPT_MAP"
    COMPARISON = "COMPARISON"
    MULTI_DOCUMENT = "MULTI_DOCUMENT"
    MULTI_HOP = "MULTI_HOP"
    AGGREGATION = "AGGREGATION"
    SUMMARY = "SUMMARY"
    QUIZ_GENERATION = "QUIZ_GENERATION"

    @property
    def needs_decomposition(self) -> bool:
        """Classes that are answered by breaking the question into sub-questions."""
        return self in {
            QueryClass.MULTI_DOCUMENT,
            QueryClass.MULTI_HOP,
            QueryClass.AGGREGATION,
            QueryClass.COMPARISON,
        }

    @property
    def benefits_from_graph(self) -> bool:
        """Classes for which graph traversal is an additional retrieval path.

        Graph retrieval is never the default; it supplements dense and keyword results
        for questions that are actually about relationships.
        """
        return self in {
            QueryClass.RELATIONSHIP,
            QueryClass.PREREQUISITE,
            QueryClass.CONCEPT_MAP,
        }

    @property
    def forbids_expansion(self) -> bool:
        """Classes where paraphrasing the query would actively harm retrieval.

        An exact quotation or identifier must be searched as written; a selected table or
        figure is already resolved and needs no broadening.
        """
        return self in {
            QueryClass.EXACT_TERM,
            QueryClass.TABLE,
            QueryClass.VISUAL,
            QueryClass.SUMMARY,
        }


class EarlyExitPath(StrEnum):
    """A shortcut past the full retrieval pipeline.

    Taken when the question has already resolved what it is about. Searching broadly for
    a table the student has selected and is pointing at wastes time and can only make the
    answer worse by surfacing something else.
    """

    TABLE_LOOKUP = "TABLE_LOOKUP"
    VISUAL_LOOKUP = "VISUAL_LOOKUP"
    EXACT_LOOKUP = "EXACT_LOOKUP"


class RetrieverKind(StrEnum):
    """Which retriever produced a ranked list.

    Fusion combines lists whose scores are not comparable, so the ranks are what merge and
    the source is what makes a result explainable afterwards.
    """

    DENSE = "DENSE"
    KEYWORD = "KEYWORD"
    GRAPH = "GRAPH"
    TABLE = "TABLE"
    VISUAL = "VISUAL"


# ---------------------------------------------------------------------------
# Generation and validation
# ---------------------------------------------------------------------------
class ClaimStatus(StrEnum):
    """Whether a single claim in an answer is carried by its cited evidence."""

    ENTAILED = "ENTAILED"
    CONTRADICTED = "CONTRADICTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class ValidationDecision(StrEnum):
    """What to do with a generated answer.

    `INSUFFICIENT_EVIDENCE` is a correct outcome, not a failure — the system saying so is
    preferable to it answering from model memory.
    """

    VALID = "VALID"
    REPAIRABLE = "REPAIRABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REJECTED = "REJECTED"

    @property
    def is_returnable(self) -> bool:
        """Whether the student sees a substantive answer.

        An abstention is returnable and is not an error; a rejection is neither.
        """
        return self in {
            ValidationDecision.VALID,
            ValidationDecision.INSUFFICIENT_EVIDENCE,
        }


class CoverageStatus(StrEnum):
    """How well the gathered evidence answers a sub-question.

    `CONFLICTING` is deliberately distinct from `UNSUPPORTED`: sources that disagree must
    be reported as disagreeing, never averaged into a consensus that no source states.
    """

    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONFLICTING = "CONFLICTING"

    @property
    def needs_another_round(self) -> bool:
        return self in {
            CoverageStatus.PARTIALLY_SUPPORTED,
            CoverageStatus.UNSUPPORTED,
        }


class RequirementLevel(IntEnum):
    """Priority of an instruction given to the model.

    Ordered, because conflicts are resolved by comparing levels. Security rules are
    critical and cannot be overridden by anything below them.
    """

    PREFERRED = 10
    REQUIRED = 20
    CRITICAL = 30


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
class MemoryType(StrEnum):
    PREFERENCE = "PREFERENCE"
    PROJECT_DECISION = "PROJECT_DECISION"
    CONSTRAINT = "CONSTRAINT"
    IDENTIFIER = "IDENTIFIER"
    GOAL = "GOAL"
    EXAM_DATE = "EXAM_DATE"
    WEAK_TOPIC = "WEAK_TOPIC"


class MemoryStatus(StrEnum):
    """Lifecycle of a durable fact.

    A corrected fact is superseded rather than overwritten, so the change stays auditable
    and an assistant guess never quietly becomes a confirmed truth.
    """

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DISPUTED = "DISPUTED"
    UNCONFIRMED = "UNCONFIRMED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"

    @property
    def is_retrievable(self) -> bool:
        """Only active memory reaches a prompt."""
        return self is MemoryStatus.ACTIVE


class MemoryProvenance(IntEnum):
    """Where a durable fact came from, ordered by how much it is trusted.

    A recent explicit correction beats a verified application event, which beats an
    earlier user statement, which beats anything the assistant inferred.
    """

    ASSISTANT_INFERENCE = 10
    USER_STATEMENT = 20
    APPLICATION_EVENT = 30
    USER_CORRECTION = 40


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------
class GraphNodeType(StrEnum):
    KNOWLEDGE_BASE = "KnowledgeBase"
    DOCUMENT = "Document"
    CHAPTER = "Chapter"
    SECTION = "Section"
    CONCEPT = "Concept"
    FIGURE = "Figure"
    TABLE = "Table"


class RelationshipType(StrEnum):
    CONTAINS = "CONTAINS"
    PART_OF = "PART_OF"
    DEFINED_IN = "DEFINED_IN"
    RELATED_TO = "RELATED_TO"
    PREREQUISITE_OF = "PREREQUISITE_OF"
    COMPARES_WITH = "COMPARES_WITH"
    EXPLAINED_BY = "EXPLAINED_BY"
    SHOWN_IN = "SHOWN_IN"
    REFERENCES = "REFERENCES"


# ---------------------------------------------------------------------------
# Model gateway
# ---------------------------------------------------------------------------
class ModelTask(StrEnum):
    """What a model is being asked to do.

    Routing is per task rather than per call site, so the smallest capable model can serve
    each one and a change of model is a change of configuration.
    """

    QUERY_REWRITE = "QUERY_REWRITE"
    QUERY_EXPANSION = "QUERY_EXPANSION"
    ANSWER_GENERATION = "ANSWER_GENERATION"
    VISUAL_QUESTION = "VISUAL_QUESTION"
    MULTI_HOP_DECOMPOSITION = "MULTI_HOP_DECOMPOSITION"
    SUMMARIZATION = "SUMMARIZATION"
    QUIZ_GENERATION = "QUIZ_GENERATION"
    MEMORY_EXTRACTION = "MEMORY_EXTRACTION"
    GRAPH_EXTRACTION = "GRAPH_EXTRACTION"
    FAITHFULNESS_CHECK = "FAITHFULNESS_CHECK"

    @property
    def requires_image_input(self) -> bool:
        return self is ModelTask.VISUAL_QUESTION


class DataBoundary(StrEnum):
    """Where a provider's inference physically happens.

    Checked before a prompt is assembled. A provider declared `THIRD_PARTY` may not
    receive private documents, memory or personal identifiers, and the system raises
    rather than rerouting silently.
    """

    LOCAL = "local"
    THIRD_PARTY = "third_party"

    @property
    def accepts_private_content(self) -> bool:
        return self is DataBoundary.LOCAL
