"""Repository ports — the persistence interfaces the domain depends on.

Every method that reads or writes scoped data takes `ScopeContext` as its first
parameter. This makes an unscoped query unrepresentable at the call site: a caller
that forgets the scope cannot satisfy the type, so the mistake is caught at type-check
time rather than in a review or at runtime.

Two deliberate exceptions to that rule:
- `KnowledgeBaseRepository.list_for_user` — listing KBs establishes the scope; there
  is no kb_id to put into a ScopeContext at that point.
- `JobRepository` worker methods (`get`, `save`, `claim_next`) — workers operate
  across users and cannot be pre-scoped. User-facing listing still uses ScopeContext.

All methods are async (D-25). The methods here are the minimum surface visible to
application-layer use cases based on the planned phases; they grow as phases are built.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.conversations.entities import Conversation, Message
from app.domain.documents.chunks import Chunk
from app.domain.documents.entities import Document, DocumentElement, DocumentPage
from app.domain.enums import JobType
from app.domain.graph.entities import GraphEntity, GraphRelationship
from app.domain.jobs.entities import ProcessingJob
from app.domain.knowledge_base.entities import KnowledgeBase
from app.domain.memory.entities import MemoryFact
from app.domain.retrieval.entities import Evidence
from app.domain.scope import ScopeContext


class KnowledgeBaseRepository(Protocol):
    """Persistence for KnowledgeBase aggregates."""

    async def get(self, scope: ScopeContext) -> KnowledgeBase | None:
        """Return the Knowledge Base identified by scope.knowledge_base_id, or None."""
        ...

    async def save(self, scope: ScopeContext, kb: KnowledgeBase) -> None:
        """Upsert a Knowledge Base."""
        ...

    async def delete(self, scope: ScopeContext) -> None:
        """Permanently remove the Knowledge Base and all its records."""
        ...

    async def list_for_user(self, user_id: UUID) -> Sequence[KnowledgeBase]:
        """All Knowledge Bases belonging to this user, newest first.

        Takes user_id directly because no KB scope exists yet at listing time.
        """
        ...


class DocumentRepository(Protocol):
    """Persistence for Document aggregates, including their pages and elements."""

    async def get(self, scope: ScopeContext, document_id: UUID) -> Document | None: ...

    async def save(self, scope: ScopeContext, document: Document) -> None: ...

    async def list(self, scope: ScopeContext) -> Sequence[Document]: ...

    async def delete(self, scope: ScopeContext, document_id: UUID) -> None: ...

    async def save_pages(
        self, scope: ScopeContext, pages: Sequence[DocumentPage]
    ) -> None: ...

    async def get_pages(
        self, scope: ScopeContext, document_id: UUID
    ) -> Sequence[DocumentPage]: ...

    async def save_elements(
        self, scope: ScopeContext, elements: Sequence[DocumentElement]
    ) -> None: ...

    async def get_elements(
        self,
        scope: ScopeContext,
        document_id: UUID,
        *,
        page_number: int | None = None,
    ) -> Sequence[DocumentElement]:
        """Elements for a document, optionally narrowed to a single page."""
        ...


class ChunkRepository(Protocol):
    """Persistence for retrievable Chunks."""

    async def get(self, scope: ScopeContext, chunk_id: UUID) -> Chunk | None: ...

    async def get_many(
        self, scope: ScopeContext, chunk_ids: Sequence[UUID]
    ) -> Sequence[Chunk]:
        """Every chunk named that the caller is allowed to see, in no particular order.

        One query rather than one per id: this exists for loading the parents of a whole
        evidence list at once, and a round trip per passage would put the database in the
        middle of a loop that runs while a student waits. Ids that do not exist, or belong
        to someone else, are simply absent from the result.
        """
        ...

    async def save_batch(
        self, scope: ScopeContext, chunks: Sequence[Chunk]
    ) -> None: ...

    async def list_for_document(
        self, scope: ScopeContext, document_id: UUID
    ) -> Sequence[Chunk]: ...

    async def delete_for_document(
        self, scope: ScopeContext, document_id: UUID
    ) -> None: ...

    async def set_embeddings(
        self,
        scope: ScopeContext,
        embeddings: Mapping[UUID, Sequence[float]],
        *,
        model_id: str,
        dimension: int,
        version: int,
    ) -> None:
        """Attach embedding vectors to chunks that were saved without them.

        Each key is a chunk id; the corresponding value is its dense vector.
        Also records which model produced the vectors and its output dimension,
        so queries can filter to chunks from a compatible index version.
        """
        ...


class ConversationRepository(Protocol):
    """Persistence for Conversations and their Messages."""

    async def get(
        self, scope: ScopeContext, conversation_id: UUID
    ) -> Conversation | None: ...

    async def save(self, scope: ScopeContext, conversation: Conversation) -> None: ...

    async def list(self, scope: ScopeContext) -> Sequence[Conversation]: ...

    async def delete(self, scope: ScopeContext, conversation_id: UUID) -> None: ...

    async def get_message(
        self, scope: ScopeContext, message_id: UUID
    ) -> Message | None: ...

    async def save_message(self, scope: ScopeContext, message: Message) -> None: ...

    async def list_messages(
        self, scope: ScopeContext, conversation_id: UUID, *, limit: int = 50
    ) -> Sequence[Message]:
        """Most recent messages first, up to limit."""
        ...

    async def save_retrieval_chunks(
        self, scope: ScopeContext, message_id: UUID, evidence: Sequence[Evidence]
    ) -> None:
        """Record exactly which chunks were in the model's context for one answer.

        Written against the assistant message, because the question this record
        exists to answer is asked about an answer: did the passage this claim cites
        actually reach the model, or did the model invent a citation to something it
        never saw? Nothing else can settle that — the prompt is gone by the time
        anyone asks, so the evidence behind it has to be durable.
        """
        ...


class ConversationUnitOfWork(Protocol):
    """Opens a conversation repository over its own transaction and commits it.

    A repository handed in ready-made borrows whoever built it — for a request-scoped
    session that means the writes are only durable while the request lasts. Streaming an
    answer outlives its request: the last token is sent, the handler has long returned,
    and only then is there an answer to store. Writes made against the request's session
    at that point are discarded.

    Producing the repository per unit of work instead of receiving one moves the
    transaction boundary to where the work actually is. Each block is a whole change,
    committed when it completes and rolled back if it raises, and none of them depend on
    a caller still being around.
    """

    def __call__(self) -> AbstractAsyncContextManager[ConversationRepository]: ...


class MemoryRepository(Protocol):
    """Persistence for MemoryFacts."""

    async def get(self, scope: ScopeContext, fact_id: UUID) -> MemoryFact | None: ...

    async def save(self, scope: ScopeContext, fact: MemoryFact) -> None: ...

    async def save_batch(
        self, scope: ScopeContext, facts: Sequence[MemoryFact]
    ) -> None: ...

    async def list_active(self, scope: ScopeContext) -> Sequence[MemoryFact]:
        """All facts with status ACTIVE, for inclusion in model context."""
        ...

    async def list_all(self, scope: ScopeContext) -> Sequence[MemoryFact]:
        """All facts regardless of status, for compaction and review."""
        ...


class GraphRepository(Protocol):
    """Persistence for GraphEntity and GraphRelationship."""

    async def get_entity(
        self, scope: ScopeContext, entity_id: UUID
    ) -> GraphEntity | None: ...

    async def save_entity(
        self, scope: ScopeContext, entity: GraphEntity
    ) -> None: ...

    async def save_entities(
        self, scope: ScopeContext, entities: Sequence[GraphEntity]
    ) -> None: ...

    async def get_relationship(
        self, scope: ScopeContext, relationship_id: UUID
    ) -> GraphRelationship | None: ...

    async def save_relationship(
        self, scope: ScopeContext, relationship: GraphRelationship
    ) -> None: ...

    async def save_relationships(
        self, scope: ScopeContext, relationships: Sequence[GraphRelationship]
    ) -> None: ...

    async def delete_for_document(
        self, scope: ScopeContext, document_id: UUID
    ) -> None:
        """Remove all entities and relationships extracted from this document."""
        ...


class JobRepository(Protocol):
    """Persistence for ProcessingJobs.

    Worker operations (`get`, `save`, `claim_next`) do not take ScopeContext because a
    worker processes jobs across all users. Scoped listing is provided for user-facing
    status queries.
    """

    async def get(self, job_id: UUID) -> ProcessingJob | None: ...

    async def save(self, job: ProcessingJob) -> None: ...

    async def claim_next(
        self,
        *,
        job_types: frozenset[JobType],
        worker_id: str,
        lease_until: datetime,
    ) -> ProcessingJob | None:
        """Atomically claim the highest-priority pending job of an eligible type.

        Returns None when no eligible job is available.
        """
        ...

    async def reclaim_expired(
        self,
        *,
        job_types: frozenset[JobType],
        now: datetime,
        backoff_base_seconds: int,
        backoff_max_seconds: int,
    ) -> Sequence[ProcessingJob]:
        """Return jobs whose worker stopped renewing their lease to the queue.

        A lease is a promise to keep working, refreshed while the work continues. One
        that lapses means the worker holding it is gone — killed, crashed, or cut off —
        and the job it was holding will otherwise sit as RUNNING for ever, because no
        worker claims a job that another one appears to be doing.

        The lapse is recorded as a failed attempt rather than as a fresh start. It was an
        attempt, and it consumed one: a job that reliably kills whatever picks it up
        would otherwise be retried for ever, always looking untried.

        Returns the jobs that were reclaimed, so a caller can say what happened.
        """
        ...

    async def list_for_scope(self, scope: ScopeContext) -> Sequence[ProcessingJob]:
        """All jobs associated with this user and Knowledge Base."""
        ...
