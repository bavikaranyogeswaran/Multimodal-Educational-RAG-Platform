"""The isolation boundary, as a value.

A Knowledge Base is the security boundary, not merely a folder. Expressing that boundary
as a required argument rather than as a convention is what makes it hard to forget: a
repository method whose first parameter is a `ScopeContext` cannot be called without one,
and a caller that has not established scope has nothing to pass.

This type is the reason the rule is checkable at all. Everything else — the predicates in
SQL, the row-level security policies — enforces the same fact a second and third time.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.domain.errors import InvariantViolationError, ScopeViolationError

_NIL_UUID = UUID(int=0)


@dataclass(frozen=True, slots=True)
class ScopeContext:
    """The authenticated user and the Knowledge Base they are operating within.

    Constructed once per request, after the access token has been verified and ownership
    checked. Never assembled from client-supplied values.
    """

    user_id: UUID
    knowledge_base_id: UUID

    def __post_init__(self) -> None:
        if self.user_id == _NIL_UUID:
            raise InvariantViolationError("ScopeContext.user_id must not be the nil UUID")
        if self.knowledge_base_id == _NIL_UUID:
            raise InvariantViolationError("ScopeContext.knowledge_base_id must not be the nil UUID")

    def owns(self, user_id: UUID, knowledge_base_id: UUID) -> bool:
        """Whether a record carrying these identifiers is inside this scope."""
        return user_id == self.user_id and knowledge_base_id == self.knowledge_base_id

    def require_ownership(
        self,
        user_id: UUID,
        knowledge_base_id: UUID,
        *,
        detail: str = "",
    ) -> None:
        """Raise unless the record belongs to this scope.

        A last line of defence rather than the first. By the time a record has been read
        it should already have been filtered; this catches the case where it was not, and
        turns a silent leak into a loud failure.
        """
        if not self.owns(user_id, knowledge_base_id):
            raise ScopeViolationError(
                expected_user_id=self.user_id,
                expected_knowledge_base_id=self.knowledge_base_id,
                actual_user_id=user_id,
                actual_knowledge_base_id=knowledge_base_id,
                detail=detail,
            )

    def __str__(self) -> str:
        """Truncated on purpose — this ends up in log lines and traces."""
        return f"user={str(self.user_id)[:8]} kb={str(self.knowledge_base_id)[:8]}"
