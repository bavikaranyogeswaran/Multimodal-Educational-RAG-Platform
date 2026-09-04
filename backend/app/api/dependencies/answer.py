"""FastAPI dependency: assemble AnswerUseCase for the stream route.

The use case is handed a unit of work rather than a repository, because its writes
straddle the end of the request. Retrieval still runs on the request's own session —
it is finished before the response starts streaming, and it only reads.

The knowledge base, graph and memory repositories are handed over on that same
request session, for the same reason: all three are read once while assembling the
prompt, before the first token leaves. Only the post-turn hook needs a session of its
own, because it runs after the response has been delivered and the request session is
long closed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import uuid
from datetime import UTC, datetime

from app.api.dependencies.container import get_container
from app.api.dependencies.retrieval import get_retrieval_orchestrator
from app.api.dependencies.scope import get_kb_scope
from app.application.commands.answer import AnswerUseCase
from app.application.commands.decompose import DecomposeQueryUseCase
from app.application.commands.embed_memory import EmbedMemoryCommand, EmbedMemoryUseCase
from app.application.commands.extract_memory import ExtractMemoryCommand, ExtractMemoryUseCase
from app.application.commands.generate_quiz import GenerateQuizUseCase
from app.application.commands.multi_hop_answer import MultiHopAnswerUseCase
from app.application.queries.coverage_classifier import CoverageClassifier
from app.application.queries.document_selection import DocumentSelector
from app.application.queries.evidence_selector import EvidenceSelector
from app.application.queries.hierarchical_synthesis import HierarchicalSynthesizer
from app.application.queries.iterative_retrieval import IterativeRetrievalLoop
from app.application.queries.retrieve_evidence import RetrievalOrchestrator
from app.application.queries.sub_question_pipeline import SubQuestionPipeline
from app.configuration.container import Container
from app.configuration.settings import get_settings
from app.domain.models.context_builder import ContextBuilder
from app.domain.scope import ScopeContext
from app.domain.enums import JobPriority, JobStatus, JobType
from app.domain.jobs.entities import ProcessingJob
from app.infrastructure.database.repositories.conversation import SqlConversationRepository
from app.infrastructure.database.repositories.conversation_summary import SqlConversationSummaryRepository
from app.infrastructure.database.repositories.graph import SqlGraphRepository
from app.infrastructure.database.repositories.job import SqlJobRepository
from app.infrastructure.database.repositories.knowledge_base import SqlKnowledgeBaseRepository
from app.infrastructure.database.repositories.memory import SqlMemoryRepository
from app.infrastructure.database.session import get_session
from app.infrastructure.database.unit_of_work import build_conversation_unit_of_work
from app.infrastructure.models.entailment import OllamaClaimEntailment
from app.infrastructure.models.faithfulness import OllamaAnswerFaithfulness

_log = structlog.get_logger(__name__)


def _build_post_turn_hook(
    session_factory: async_sessionmaker[AsyncSession],
    scope: ScopeContext,
    container: Container,
) -> Callable[[ScopeContext, UUID], Awaitable[None]]:
    """Build a post-turn callable that extracts memory facts and triggers compaction.

    Opened sessions are committed independently: extraction writes facts (and
    optionally enqueues a compaction job) in the first session, embedding updates
    the vectors in the second. Splitting the commits avoids a long-lived transaction
    that would hold locks across LLM calls.
    """
    extractor = container.memory_extractor
    assert extractor is not None
    embedder = container.embedder
    summarizer = container.summarizer

    async def _hook(hook_scope: ScopeContext, assistant_id: UUID) -> None:
        settings = get_settings()

        # Extract memory facts from the completed turn.
        async with session_factory() as session:
            conv_repo = SqlConversationRepository(scope=hook_scope, session=session)
            memory_repo = SqlMemoryRepository(scope=hook_scope, session=session)
            extract_uc = ExtractMemoryUseCase(
                conversation_repo=conv_repo,
                memory_repo=memory_repo,
                extractor=extractor,
            )
            result = await extract_uc.execute(
                ExtractMemoryCommand(scope=hook_scope, message_id=assistant_id)
            )

            # Enqueue compaction when the message count crosses the configured
            # threshold. The check runs in the same transaction so the job is only
            # enqueued when extraction succeeded.
            if result.conversation_id is not None and summarizer is not None:
                threshold = settings.memory.compaction_unsummarized_messages
                count = await conv_repo.count_messages(
                    hook_scope, result.conversation_id
                )
                if count >= threshold and count % threshold == 0:
                    now = datetime.now(UTC)
                    await SqlJobRepository(session).save(
                        ProcessingJob(
                            id=uuid.uuid4(),
                            job_type=JobType.COMPACT_MEMORY,
                            priority=JobPriority.BACKGROUND,
                            status=JobStatus.PENDING,
                            attempt_count=0,
                            max_attempts=settings.job.max_attempts,
                            created_at=now,
                            updated_at=now,
                            payload={
                                "conversation_id": str(result.conversation_id),
                                "user_id": str(hook_scope.user_id),
                                "knowledge_base_id": str(hook_scope.knowledge_base_id),
                            },
                        )
                    )

            await session.commit()

        if not result.embeddable_ids:
            return

        # Embed the newly written facts in a separate session.
        async with session_factory() as session:
            memory_repo = SqlMemoryRepository(scope=hook_scope, session=session)
            embed_uc = EmbedMemoryUseCase(memory_repo=memory_repo, embedder=embedder)
            await embed_uc.execute(
                EmbedMemoryCommand(scope=hook_scope, fact_ids=result.embeddable_ids)
            )
            await session.commit()

    return _hook


async def get_answer_use_case(
    retrieve: Annotated[RetrievalOrchestrator, Depends(get_retrieval_orchestrator)],
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
    container: Annotated[Container, Depends(get_container)],
) -> AnswerUseCase:
    settings = get_settings()

    post_turn_hook = None
    if container.memory_extractor is not None:
        post_turn_hook = _build_post_turn_hook(
            session_factory=container.session_factory,
            scope=scope,
            container=container,
        )

    multi_hop = MultiHopAnswerUseCase(
        decompose=DecomposeQueryUseCase(container.query_decomposition),
        loop=IterativeRetrievalLoop(
            pipeline=SubQuestionPipeline(retrieve),
            classifier=CoverageClassifier(container.coverage_classifier),
            selector=DocumentSelector(
                max_documents=settings.multihop.max_documents_per_round
            ),
        ),
        selector=EvidenceSelector(
            max_per_sub_question=settings.evidence.max_items
        ),
        synthesizer=HierarchicalSynthesizer(container.multi_hop_synthesis),
    )

    return AnswerUseCase(
        retrieve=retrieve,
        conversation_uow=build_conversation_unit_of_work(container.session_factory, scope),
        model_gateway=container.model_gateway,
        context_builder=ContextBuilder(
            container.token_counter.count,
            token_budget=settings.model.prompt_token_budget,
        ),
        entailment=OllamaClaimEntailment(container.model_gateway),
        faithfulness=OllamaAnswerFaithfulness(container.model_gateway),
        # The knowledge base repository is what gates graph retrieval: the answer path
        # reads graph_enabled from it and skips the whole graph step when it is off, so
        # a student who never asked for a concept graph pays nothing for one existing.
        kb_repo=SqlKnowledgeBaseRepository(scope, session),
        graph_repo=SqlGraphRepository(scope, session),
        memory_repo=SqlMemoryRepository(scope, session),
        summary_repo=SqlConversationSummaryRepository(scope, session),
        multi_hop=multi_hop,
        embedder=container.embedder,
        quiz_generator=GenerateQuizUseCase(
            model_gateway=container.model_gateway,
            context_builder=ContextBuilder(
                container.token_counter.count,
                token_budget=settings.model.prompt_token_budget,
            ),
        ),
        answer_max_words=settings.generation.answer_max_words,
        answer_max_tokens=settings.generation.answer_max_tokens,
        post_turn_hook=post_turn_hook,
        # Only pass the cache when it is actually configured — storage or database
        # must be wired, otherwise container.cache is _Unimplemented.
        cache=container.cache if (
            settings.cache.enabled
            and (settings.storage.account_id or settings.database.url.get_secret_value())
        ) else None,
        cache_ttl_seconds=settings.cache.answer_ttl_seconds,
        index_version=settings.embedding.index_version,
        generation_policy_version=settings.app.generation_policy_version,
    )
