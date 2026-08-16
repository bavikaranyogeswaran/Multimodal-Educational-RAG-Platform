"""Transaction boundaries for work that outlives the request that started it.

The session dependency gives a handler one session and closes it when the response is
done. That fits a handler that reads, writes and returns. It does not fit streaming an
answer, where the writes worth keeping — the answer itself, and the record of what the
model was shown — only exist once the last token has been sent and the handler has
already returned.

A unit of work opens its own session from the application-scoped factory, so the only
thing it depends on outliving it is the engine, which lives as long as the process.
The block commits when it completes and rolls back if it raises.

This is the same shape the ingestion worker uses, for the same reason: work that is not
bounded by a request should not borrow a request's transaction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.ports.repositories import ConversationRepository
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.conversation import SqlConversationRepository


def build_conversation_unit_of_work(
    session_factory: async_sessionmaker[AsyncSession],
    scope: ScopeContext,
) -> Callable[[], AbstractAsyncContextManager[ConversationRepository]]:
    """Return a callable that opens one committed transaction per use.

    The scope is bound once, here, rather than passed in per block — the repository is
    built inside and would otherwise have to be trusted to receive the right one.
    """

    @asynccontextmanager
    async def _unit_of_work() -> AsyncIterator[ConversationRepository]:
        async with session_factory() as session:
            yield SqlConversationRepository(scope=scope, session=session)
            # Reached only when the block completed. An exception propagates through the
            # yield instead, and the session closes without committing.
            await session.commit()

    return _unit_of_work
