"""The isolation boundary.

Cross-scope access is the failure this system most needs to make impossible, so the tests
that cover it are marked as security tests and run with the rest of that suite.
"""

from __future__ import annotations

import dataclasses
from uuid import UUID, uuid4

import pytest

from app.domain.errors import InvariantViolationError, ScopeViolationError
from app.domain.scope import ScopeContext

NIL = UUID(int=0)


@pytest.fixture
def scope() -> ScopeContext:
    return ScopeContext(user_id=uuid4(), knowledge_base_id=uuid4())


class TestConstruction:
    def test_rejects_nil_user_id(self) -> None:
        with pytest.raises(InvariantViolationError, match="user_id"):
            ScopeContext(user_id=NIL, knowledge_base_id=uuid4())

    def test_rejects_nil_knowledge_base_id(self) -> None:
        with pytest.raises(InvariantViolationError, match="knowledge_base_id"):
            ScopeContext(user_id=uuid4(), knowledge_base_id=NIL)

    def test_is_immutable(self, scope: ScopeContext) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            scope.user_id = uuid4()  # type: ignore[misc]

    def test_compares_by_value(self) -> None:
        user, kb = uuid4(), uuid4()
        assert ScopeContext(user, kb) == ScopeContext(user, kb)

    def test_is_hashable_so_it_can_key_a_cache(self) -> None:
        user, kb = uuid4(), uuid4()
        assert len({ScopeContext(user, kb), ScopeContext(user, kb)}) == 1


@pytest.mark.security
class TestOwnership:
    def test_accepts_a_record_inside_the_scope(self, scope: ScopeContext) -> None:
        assert scope.owns(scope.user_id, scope.knowledge_base_id)
        scope.require_ownership(scope.user_id, scope.knowledge_base_id)

    def test_rejects_another_users_record(self, scope: ScopeContext) -> None:
        with pytest.raises(ScopeViolationError):
            scope.require_ownership(uuid4(), scope.knowledge_base_id)

    def test_rejects_another_knowledge_base_belonging_to_the_same_user(
        self, scope: ScopeContext
    ) -> None:
        """The boundary is the Knowledge Base, not the account.

        A student's own second Knowledge Base is as out of scope as a stranger's.
        """
        with pytest.raises(ScopeViolationError):
            scope.require_ownership(scope.user_id, uuid4())

    def test_violation_carries_both_sides_for_investigation(self, scope: ScopeContext) -> None:
        intruder_kb = uuid4()

        with pytest.raises(ScopeViolationError) as caught:
            scope.require_ownership(scope.user_id, intruder_kb)

        error = caught.value
        assert error.expected_knowledge_base_id == scope.knowledge_base_id
        assert error.actual_knowledge_base_id == intruder_kb


def test_string_form_truncates_identifiers(scope: ScopeContext) -> None:
    """This ends up in log lines; full identifiers there are noise, not information."""
    rendered = str(scope)

    assert str(scope.user_id) not in rendered
    assert str(scope.user_id)[:8] in rendered
