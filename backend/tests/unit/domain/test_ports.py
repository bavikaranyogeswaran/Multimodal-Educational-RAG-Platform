"""Repository port structural tests.

The central requirement: every scoped method has `ScopeContext` as its first
positional parameter after `self`. This is verified at test time via `inspect`, so
that a future edit to a method signature that drops the scope is caught immediately.

The typed stubs at the end of the module satisfy every protocol. mypy verifies this
at type-check time — if a stub is incomplete or uses the wrong type for a parameter,
mypy reports an error on the stub class.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.domain.conversations.entities import Conversation, Message
from app.domain.documents.chunks import Chunk
from app.domain.documents.entities import Document, DocumentElement, DocumentPage
from app.domain.enums import JobType
from app.domain.graph.entities import GraphEntity, GraphRelationship
from app.domain.jobs.entities import ProcessingJob
from app.domain.knowledge_base.entities import KnowledgeBase
from app.domain.memory.entities import MemoryFact
from app.domain.ports.repositories import (
    ChunkRepository,
    ConversationRepository,
    DocumentRepository,
    GraphRepository,
    JobRepository,
    KnowledgeBaseRepository,
    MemoryRepository,
)
from app.domain.scope import ScopeContext


def _first_non_self_param(method: Any) -> str:
    sig = inspect.signature(method)
    params = list(sig.parameters)
    # params[0] is always 'self'
    return params[1] if len(params) > 1 else ""


# ---------------------------------------------------------------------------
# KnowledgeBaseRepository
# ---------------------------------------------------------------------------

class TestKnowledgeBaseRepositorySignatures:
    def test_get_has_scope_first(self) -> None:
        assert _first_non_self_param(KnowledgeBaseRepository.get) == "scope"

    def test_save_has_scope_first(self) -> None:
        assert _first_non_self_param(KnowledgeBaseRepository.save) == "scope"

    def test_delete_has_scope_first(self) -> None:
        assert _first_non_self_param(KnowledgeBaseRepository.delete) == "scope"

    def test_list_for_user_takes_user_id(self) -> None:
        # Documented exception: listing establishes scope, no kb_id available yet.
        assert _first_non_self_param(KnowledgeBaseRepository.list_for_user) == "user_id"


# ---------------------------------------------------------------------------
# DocumentRepository
# ---------------------------------------------------------------------------

class TestDocumentRepositorySignatures:
    @pytest.mark.parametrize("method_name", [
        "get", "save", "list", "delete", "delete_parse",
        "save_pages", "get_pages", "save_elements", "get_elements",
    ])
    def test_method_has_scope_first(self, method_name: str) -> None:
        method = getattr(DocumentRepository, method_name)
        assert _first_non_self_param(method) == "scope", (
            f"DocumentRepository.{method_name} must take scope as first parameter"
        )


# ---------------------------------------------------------------------------
# ChunkRepository
# ---------------------------------------------------------------------------

class TestChunkRepositorySignatures:
    @pytest.mark.parametrize("method_name", [
        "get", "save_batch", "list_for_document", "delete_for_document",
    ])
    def test_method_has_scope_first(self, method_name: str) -> None:
        method = getattr(ChunkRepository, method_name)
        assert _first_non_self_param(method) == "scope"


# ---------------------------------------------------------------------------
# ConversationRepository
# ---------------------------------------------------------------------------

class TestConversationRepositorySignatures:
    @pytest.mark.parametrize("method_name", [
        "get", "save", "list", "delete",
        "get_message", "save_message", "list_messages",
    ])
    def test_method_has_scope_first(self, method_name: str) -> None:
        method = getattr(ConversationRepository, method_name)
        assert _first_non_self_param(method) == "scope"


# ---------------------------------------------------------------------------
# MemoryRepository
# ---------------------------------------------------------------------------

class TestMemoryRepositorySignatures:
    @pytest.mark.parametrize("method_name", [
        "get", "save", "save_batch", "list_active", "list_all",
    ])
    def test_method_has_scope_first(self, method_name: str) -> None:
        method = getattr(MemoryRepository, method_name)
        assert _first_non_self_param(method) == "scope"


# ---------------------------------------------------------------------------
# GraphRepository
# ---------------------------------------------------------------------------

class TestGraphRepositorySignatures:
    @pytest.mark.parametrize("method_name", [
        "get_entity", "save_entity", "save_entities",
        "get_relationship", "save_relationship", "save_relationships",
        "delete_for_document",
    ])
    def test_method_has_scope_first(self, method_name: str) -> None:
        method = getattr(GraphRepository, method_name)
        assert _first_non_self_param(method) == "scope"


# ---------------------------------------------------------------------------
# JobRepository — documented exception for worker-level methods
# ---------------------------------------------------------------------------

class TestJobRepositorySignatures:
    def test_get_takes_job_id_not_scope(self) -> None:
        # Deliberate exception: workers operate across all users.
        assert _first_non_self_param(JobRepository.get) == "job_id"

    def test_save_takes_job_not_scope(self) -> None:
        assert _first_non_self_param(JobRepository.save) == "job"

    def test_list_for_scope_has_scope_first(self) -> None:
        assert _first_non_self_param(JobRepository.list_for_scope) == "scope"


# ---------------------------------------------------------------------------
# Typed stubs — mypy verifies these at type-check time.
#
# Each stub is a complete implementation of its protocol using only the method
# signatures. The body of every method raises NotImplementedError so that calling
# one accidentally in a test fails loudly instead of silently returning None.
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


class _StubKnowledgeBaseRepository:
    async def get(self, scope: ScopeContext) -> KnowledgeBase | None:
        raise NotImplementedError

    async def save(self, scope: ScopeContext, kb: KnowledgeBase) -> None:
        raise NotImplementedError

    async def delete(self, scope: ScopeContext) -> None:
        raise NotImplementedError

    async def list_for_user(self, user_id: UUID) -> Sequence[KnowledgeBase]:
        raise NotImplementedError


class _StubDocumentRepository:
    async def get(self, scope: ScopeContext, document_id: UUID) -> Document | None:
        raise NotImplementedError

    async def save(self, scope: ScopeContext, document: Document) -> None:
        raise NotImplementedError

    async def list(self, scope: ScopeContext) -> Sequence[Document]:
        raise NotImplementedError

    async def delete(self, scope: ScopeContext, document_id: UUID) -> None:
        raise NotImplementedError

    async def save_pages(
        self, scope: ScopeContext, pages: Sequence[DocumentPage]
    ) -> None:
        raise NotImplementedError

    async def get_pages(
        self, scope: ScopeContext, document_id: UUID
    ) -> Sequence[DocumentPage]:
        raise NotImplementedError

    async def save_elements(
        self, scope: ScopeContext, elements: Sequence[DocumentElement]
    ) -> None:
        raise NotImplementedError

    async def get_elements(
        self,
        scope: ScopeContext,
        document_id: UUID,
        *,
        page_number: int | None = None,
    ) -> Sequence[DocumentElement]:
        raise NotImplementedError

    async def delete_parse(self, scope: ScopeContext, document_id: UUID) -> None:
        raise NotImplementedError


class _StubChunkRepository:
    async def get(self, scope: ScopeContext, chunk_id: UUID) -> Chunk | None:
        raise NotImplementedError

    async def save_batch(self, scope: ScopeContext, chunks: Sequence[Chunk]) -> None:
        raise NotImplementedError

    async def list_for_document(
        self, scope: ScopeContext, document_id: UUID
    ) -> Sequence[Chunk]:
        raise NotImplementedError

    async def delete_for_document(
        self, scope: ScopeContext, document_id: UUID
    ) -> None:
        raise NotImplementedError


class _StubConversationRepository:
    async def get(
        self, scope: ScopeContext, conversation_id: UUID
    ) -> Conversation | None:
        raise NotImplementedError

    async def save(self, scope: ScopeContext, conversation: Conversation) -> None:
        raise NotImplementedError

    async def list(self, scope: ScopeContext) -> Sequence[Conversation]:
        raise NotImplementedError

    async def delete(self, scope: ScopeContext, conversation_id: UUID) -> None:
        raise NotImplementedError

    async def get_message(
        self, scope: ScopeContext, message_id: UUID
    ) -> Message | None:
        raise NotImplementedError

    async def save_message(self, scope: ScopeContext, message: Message) -> None:
        raise NotImplementedError

    async def list_messages(
        self, scope: ScopeContext, conversation_id: UUID, *, limit: int = 50
    ) -> Sequence[Message]:
        raise NotImplementedError


class _StubMemoryRepository:
    async def get(self, scope: ScopeContext, fact_id: UUID) -> MemoryFact | None:
        raise NotImplementedError

    async def save(self, scope: ScopeContext, fact: MemoryFact) -> None:
        raise NotImplementedError

    async def save_batch(
        self, scope: ScopeContext, facts: Sequence[MemoryFact]
    ) -> None:
        raise NotImplementedError

    async def list_active(self, scope: ScopeContext) -> Sequence[MemoryFact]:
        raise NotImplementedError

    async def list_all(self, scope: ScopeContext) -> Sequence[MemoryFact]:
        raise NotImplementedError


class _StubGraphRepository:
    async def get_entity(
        self, scope: ScopeContext, entity_id: UUID
    ) -> GraphEntity | None:
        raise NotImplementedError

    async def save_entity(self, scope: ScopeContext, entity: GraphEntity) -> None:
        raise NotImplementedError

    async def save_entities(
        self, scope: ScopeContext, entities: Sequence[GraphEntity]
    ) -> None:
        raise NotImplementedError

    async def get_relationship(
        self, scope: ScopeContext, relationship_id: UUID
    ) -> GraphRelationship | None:
        raise NotImplementedError

    async def save_relationship(
        self, scope: ScopeContext, relationship: GraphRelationship
    ) -> None:
        raise NotImplementedError

    async def save_relationships(
        self, scope: ScopeContext, relationships: Sequence[GraphRelationship]
    ) -> None:
        raise NotImplementedError

    async def delete_for_document(
        self, scope: ScopeContext, document_id: UUID
    ) -> None:
        raise NotImplementedError


class _StubJobRepository:
    async def get(self, job_id: UUID) -> ProcessingJob | None:
        raise NotImplementedError

    async def save(self, job: ProcessingJob) -> None:
        raise NotImplementedError

    async def claim_next(
        self,
        *,
        job_types: frozenset[JobType],
        worker_id: str,
        lease_until: datetime,
    ) -> ProcessingJob | None:
        raise NotImplementedError

    async def list_for_scope(self, scope: ScopeContext) -> Sequence[ProcessingJob]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Mypy-level compliance — these assignments are type-checked.
# ---------------------------------------------------------------------------

_kb_repo: KnowledgeBaseRepository = _StubKnowledgeBaseRepository()
_doc_repo: DocumentRepository = _StubDocumentRepository()
_chunk_repo: ChunkRepository = _StubChunkRepository()
_conv_repo: ConversationRepository = _StubConversationRepository()
_mem_repo: MemoryRepository = _StubMemoryRepository()
_graph_repo: GraphRepository = _StubGraphRepository()
_job_repo: JobRepository = _StubJobRepository()


class TestProtocolCompliance:
    """Verify the stubs can be assigned to protocol-typed variables at runtime.

    The structural check is already done by mypy. These tests confirm that the
    stub classes exist and are instantiable, which is a necessary condition for
    being valid implementations.
    """

    def test_knowledge_base_stub_is_instantiable(self) -> None:
        assert _StubKnowledgeBaseRepository() is not None

    def test_document_stub_is_instantiable(self) -> None:
        assert _StubDocumentRepository() is not None

    def test_chunk_stub_is_instantiable(self) -> None:
        assert _StubChunkRepository() is not None

    def test_conversation_stub_is_instantiable(self) -> None:
        assert _StubConversationRepository() is not None

    def test_memory_stub_is_instantiable(self) -> None:
        assert _StubMemoryRepository() is not None

    def test_graph_stub_is_instantiable(self) -> None:
        assert _StubGraphRepository() is not None

    def test_job_stub_is_instantiable(self) -> None:
        assert _StubJobRepository() is not None
