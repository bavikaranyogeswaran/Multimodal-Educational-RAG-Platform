"""FastAPI dependency: assemble AnswerUseCase for the stream route.

The use case is handed a unit of work rather than a repository, because its writes
straddle the end of the request. Retrieval still runs on the request's own session —
it is finished before the response starts streaming, and it only reads.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies.container import get_container
from app.api.dependencies.retrieval import get_retrieval_orchestrator
from app.api.dependencies.scope import get_kb_scope
from app.application.commands.answer import AnswerUseCase
from app.application.commands.embed_memory import EmbedMemoryCommand, EmbedMemoryUseCase
from app.application.commands.extract_memory import ExtractMemoryCommand, ExtractMemoryUseCase
from app.application.queries.retrieve_evidence import RetrievalOrchestrator
from app.configuration.container import Container
from app.configuration.settings import get_settings
from app.domain.models.context_builder import ContextBuilder
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.conversation import SqlConversationRepository
from app.infrastructure.database.repositories.memory import SqlMemoryRepository
from app.infrastructure.database.unit_of_work import build_conversation_unit_of_work
from app.infrastructure.models.entailment import OllamaClaimEntailment
from app.infrastructure.models.faithfulness import OllamaAnswerFaithfulness

_log = structlog.get_logger(__name__)


def _build_post_turn_hook(
    session_factory: async_sessionmaker[AsyncSession],
    scope: ScopeContext,
    container: Container,
) -> Callable[[ScopeContext, UUID], Awaitable[None]]:
    """Build a post-turn callable that extracts and embeds memory facts.

    Opened sessions are committed independently: extraction writes facts, then a
    fresh session for embedding reads and updates them. Splitting the commits
    avoids a long-lived transaction that would hold locks across LLM calls.
    """
    extractor = container.memory_extractor
    assert extractor is not None  # caller guards this with `if container.memory_extractor is not None`
    embedder = container.embedder

    async def _hook(hook_scope: ScopeContext, assistant_id: UUID) -> None:
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
        answer_max_words=settings.generation.answer_max_words,
        answer_max_tokens=settings.generation.answer_max_tokens,
        post_turn_hook=post_turn_hook,
    )
