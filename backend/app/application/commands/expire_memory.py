"""Use case: mark memory facts as EXPIRED when their expiry deadline has passed.

Intended to run as a periodic background job. It loads all ACTIVE facts for
the given scope whose expires_at is at or before the supplied cutoff, calls
mark_expired() on each, and saves the results in a single batch. Facts that
are already in a terminal status (SUPERSEDED, EXPIRED, DELETED) are never
returned by list_expiring, so the use case never double-transitions a fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.ports.repositories import MemoryRepository
from app.domain.scope import ScopeContext


@dataclass(frozen=True)
class ExpireMemoryCommand:
    scope: ScopeContext
    cutoff: datetime


@dataclass(frozen=True)
class ExpireMemoryResult:
    expired: int


class ExpireMemoryUseCase:
    """Transition ACTIVE facts whose deadline has passed into EXPIRED status."""

    def __init__(self, memory_repo: MemoryRepository) -> None:
        self._memory_repo = memory_repo

    async def execute(self, command: ExpireMemoryCommand) -> ExpireMemoryResult:
        scope = command.scope
        now = command.cutoff

        due = await self._memory_repo.list_expiring(scope, before=now)
        if not due:
            return ExpireMemoryResult(expired=0)

        expired_facts = [fact.mark_expired(now=now) for fact in due]
        await self._memory_repo.save_batch(scope, expired_facts)

        return ExpireMemoryResult(expired=len(expired_facts))
