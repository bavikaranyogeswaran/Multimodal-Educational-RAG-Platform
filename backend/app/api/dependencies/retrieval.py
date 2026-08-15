"""FastAPI dependency: assemble RetrieveEvidenceUseCase for route handlers.

SqlDenseRetriever is per-request (it holds a scoped DB session), so it is
constructed here rather than stored as a singleton in the container.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.container import get_container
from app.api.dependencies.scope import get_kb_scope
from app.application.queries.retrieve_evidence import RetrieveEvidenceUseCase
from app.configuration.container import Container
from app.domain.scope import ScopeContext
from app.infrastructure.database.session import get_session
from app.infrastructure.retrieval.dense import SqlDenseRetriever


async def get_retrieve_evidence_use_case(
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
    container: Annotated[Container, Depends(get_container)],
) -> RetrieveEvidenceUseCase:
    return RetrieveEvidenceUseCase(
        embedder=container.embedder,
        dense_retriever=SqlDenseRetriever(scope=scope, session=session),
    )
