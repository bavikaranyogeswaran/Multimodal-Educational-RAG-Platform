"""FastAPI dependency: assemble AnswerUseCase for the stream route.

SqlConversationRepository is per-request (holds a scoped DB session), so it is
constructed here alongside the other per-request collaborators.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.container import get_container
from app.api.dependencies.retrieval import get_retrieve_evidence_use_case
from app.api.dependencies.scope import get_kb_scope
from app.application.commands.answer import AnswerUseCase
from app.application.queries.retrieve_evidence import RetrieveEvidenceUseCase
from app.configuration.container import Container
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.conversation import SqlConversationRepository
from app.infrastructure.database.session import get_session


async def get_answer_use_case(
    retrieve: Annotated[RetrieveEvidenceUseCase, Depends(get_retrieve_evidence_use_case)],
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
    container: Annotated[Container, Depends(get_container)],
) -> AnswerUseCase:
    return AnswerUseCase(
        retrieve=retrieve,
        conversation_repo=SqlConversationRepository(scope=scope, session=session),
        model_gateway=container.model_gateway,
    )
