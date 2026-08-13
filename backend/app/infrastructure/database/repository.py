"""ScopedRepository — shared base for all scoped SQLAlchemy repositories.

Every concrete repository that operates within a user/knowledge-base scope
inherits from this class. It stores the ScopeContext and AsyncSession, and
provides filter-building helpers that concrete repositories must call on every
SELECT. Requiring an explicit helper call rather than writing WHERE clauses
inline makes an accidentally unscoped query visible in code review rather than
silently absent.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import InvariantViolationError
from app.domain.scope import ScopeContext


class ScopedRepository:
    """Base class for repositories that are bound to a ScopeContext.

    Carries shared implementation, not an interface — the repository contracts
    themselves are the Protocols in the domain layer, which concrete subclasses
    satisfy structurally.

    Constructed once per request, after the scope has been established. Raises
    InvariantViolationError at construction time if anything other than a
    ScopeContext is passed, so the error surfaces at the composition root
    rather than later as a silent wrong-user query.
    """

    def __init__(self, scope: ScopeContext, session: AsyncSession) -> None:
        if not isinstance(scope, ScopeContext):
            raise InvariantViolationError(
                f"ScopedRepository requires a ScopeContext, got {type(scope).__name__}"
            )
        self._scope = scope
        self._session = session

    def _require_scope(self, scope: ScopeContext) -> None:
        """Reject a call whose scope differs from the one this repository holds.

        Every method takes a scope as its first argument, but the filters are built
        from the scope the repository was constructed with. Without this check the
        two could disagree and the query would quietly run under the bound scope —
        returning another user's rows to a caller who asked for their own. Comparing
        them makes that disagreement a loud failure at the call site instead.
        """
        self._scope.require_ownership(
            scope.user_id,
            scope.knowledge_base_id,
            detail=f"{type(self).__name__} is bound to a different scope",
        )

    def _scope_filter(self, model: type[Any]) -> ColumnElement[bool]:
        """AND filter for tables with both user_id and knowledge_base_id columns.

        Returns the conjunction user_id = :user_id AND knowledge_base_id = :kb_id
        ready to be passed to .where(). Use for every scoped table except
        knowledge_bases itself, which uses _user_filter because its scope is
        expressed as id = :kb_id, not knowledge_base_id = :kb_id.
        """
        return sa.and_(
            model.user_id == self._scope.user_id,
            model.knowledge_base_id == self._scope.knowledge_base_id,
        )

    def _user_filter(self, model: type[Any]) -> ColumnElement[bool]:
        """Filter for tables with only a user_id column.

        Used by KnowledgeBaseRepository where the scope is user-only at listing
        time and id-based at get/save/delete time.
        """
        return model.user_id == self._scope.user_id  # type: ignore[no-any-return]
