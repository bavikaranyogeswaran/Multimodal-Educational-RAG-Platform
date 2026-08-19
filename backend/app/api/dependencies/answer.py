"""FastAPI dependency: assemble AnswerUseCase for the stream route.

The use case is handed a unit of work rather than a repository, because its writes
straddle the end of the request. Retrieval still runs on the request's own session —
it is finished before the response starts streaming, and it only reads.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.api.dependencies.container import get_container
from app.api.dependencies.retrieval import get_retrieval_orchestrator
from app.api.dependencies.scope import get_kb_scope
from app.application.commands.answer import AnswerUseCase
from app.application.queries.retrieve_evidence import RetrievalOrchestrator
from app.configuration.container import Container
from app.configuration.settings import get_settings
from app.domain.models.context_builder import ContextBuilder
from app.domain.scope import ScopeContext
from app.infrastructure.database.unit_of_work import build_conversation_unit_of_work


async def get_answer_use_case(
    retrieve: Annotated[RetrievalOrchestrator, Depends(get_retrieval_orchestrator)],
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    container: Annotated[Container, Depends(get_container)],
) -> AnswerUseCase:
    settings = get_settings()
    return AnswerUseCase(
        retrieve=retrieve,
        conversation_uow=build_conversation_unit_of_work(container.session_factory, scope),
        model_gateway=container.model_gateway,
        context_builder=ContextBuilder(
            container.token_counter.count,
            token_budget=settings.model.prompt_token_budget,
        ),
    )
