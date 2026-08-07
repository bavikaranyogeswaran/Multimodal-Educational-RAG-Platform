"""MemoryFact lifecycle — especially the supersession chain.

The supersession rule: a correction produces two records — the old fact retired and the
new fact active. Neither can disappear; the audit chain is structural.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from app.domain.enums import MemoryProvenance, MemoryStatus, MemoryType
from app.domain.errors import InvariantViolationError
from app.domain.memory.entities import MemoryFact

from .conftest import LATER, NOW, Builder


class TestMemoryFactConstruction:
    def test_rejects_blank_content(self, make_memory_fact: Builder[MemoryFact]) -> None:
        with pytest.raises(InvariantViolationError, match="content"):
            make_memory_fact(content="  ")

    def test_rejects_a_naive_valid_from(self, make_memory_fact: Builder[MemoryFact]) -> None:
        with pytest.raises(InvariantViolationError):
            make_memory_fact(valid_from=datetime(2026, 1, 1))  # noqa: DTZ001

    def test_superseded_status_requires_a_replacement_id(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        with pytest.raises(InvariantViolationError, match="superseded"):
            make_memory_fact(status=MemoryStatus.SUPERSEDED, superseded_by=None)

    def test_active_status_must_not_carry_a_replacement_id(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        with pytest.raises(InvariantViolationError, match="superseded_by"):
            make_memory_fact(status=MemoryStatus.ACTIVE, superseded_by=uuid4())

    def test_valid_until_must_follow_valid_from(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        with pytest.raises(InvariantViolationError):
            make_memory_fact(valid_from=LATER, valid_until=NOW)

    def test_an_indefinite_fact_has_no_valid_until(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        fact = make_memory_fact()
        assert fact.valid_until is None

    def test_scope_derives_from_the_stored_identifiers(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        fact = make_memory_fact()
        assert fact.scope.user_id == fact.user_id
        assert fact.scope.knowledge_base_id == fact.knowledge_base_id


@pytest.mark.security
class TestSupersession:
    def test_returns_a_retired_fact_and_its_active_successor(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        fact = make_memory_fact()
        successor_id = uuid4()

        retired, successor = fact.create_successor(
            successor_id=successor_id,
            content="Corrected: student prefers review every two days, not every day.",
            provenance=MemoryProvenance.USER_CORRECTION,
            now=LATER,
        )

        assert retired.status is MemoryStatus.SUPERSEDED
        assert retired.superseded_by == successor_id
        assert successor.id == successor_id
        assert successor.status is MemoryStatus.ACTIVE

    def test_the_original_fact_is_not_mutated(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        fact = make_memory_fact()
        original_content = fact.content
        original_status = fact.status

        fact.create_successor(
            successor_id=uuid4(),
            content="new content",
            provenance=MemoryProvenance.USER_CORRECTION,
            now=LATER,
        )

        assert fact.content == original_content
        assert fact.status is original_status

    def test_the_successor_inherits_scope_and_type(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        fact = make_memory_fact(memory_type=MemoryType.WEAK_TOPIC)
        _, successor = fact.create_successor(
            successor_id=uuid4(),
            content="Thermodynamics is the weak topic, not kinematics.",
            provenance=MemoryProvenance.USER_CORRECTION,
            now=LATER,
        )

        assert successor.memory_type is MemoryType.WEAK_TOPIC
        assert successor.user_id == fact.user_id
        assert successor.knowledge_base_id == fact.knowledge_base_id

    def test_the_successor_has_fresh_timestamps(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        fact = make_memory_fact()
        _, successor = fact.create_successor(
            successor_id=uuid4(),
            content="updated content",
            provenance=MemoryProvenance.USER_CORRECTION,
            now=LATER,
        )

        assert successor.created_at == LATER
        assert successor.valid_from == LATER

    def test_a_fact_cannot_supersede_itself(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        fact = make_memory_fact()
        with pytest.raises(InvariantViolationError, match="itself"):
            fact.create_successor(
                successor_id=fact.id,
                content="same content",
                provenance=MemoryProvenance.USER_CORRECTION,
                now=LATER,
            )

    def test_only_active_facts_may_have_successors(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        expired = make_memory_fact(status=MemoryStatus.EXPIRED)
        with pytest.raises(InvariantViolationError):
            expired.create_successor(
                successor_id=uuid4(),
                content="new content",
                provenance=MemoryProvenance.USER_CORRECTION,
                now=LATER,
            )

    def test_a_superseded_fact_is_not_retrievable(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        fact = make_memory_fact()
        retired, _ = fact.create_successor(
            successor_id=uuid4(),
            content="corrected content",
            provenance=MemoryProvenance.USER_CORRECTION,
            now=LATER,
        )

        assert not retired.status.is_retrievable

    def test_only_the_active_successor_reaches_a_prompt(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        """The old fact stays in the database but is excluded from retrieval."""
        fact = make_memory_fact()
        retired, successor = fact.create_successor(
            successor_id=uuid4(),
            content="corrected content",
            provenance=MemoryProvenance.USER_CORRECTION,
            now=LATER,
        )

        assert successor.status.is_retrievable
        assert not retired.status.is_retrievable


class TestProvenanceOrdering:
    def test_correction_outranks_user_statement(self) -> None:
        assert MemoryProvenance.USER_CORRECTION > MemoryProvenance.USER_STATEMENT

    def test_user_statement_outranks_assistant_inference(self) -> None:
        assert MemoryProvenance.USER_STATEMENT > MemoryProvenance.ASSISTANT_INFERENCE

    def test_application_event_outranks_user_statement(self) -> None:
        assert MemoryProvenance.APPLICATION_EVENT > MemoryProvenance.USER_STATEMENT


class TestMemoryFactLifecycle:
    def test_active_fact_is_retrievable(self, make_memory_fact: Builder[MemoryFact]) -> None:
        assert make_memory_fact().status.is_retrievable

    def test_mark_disputed_from_active(self, make_memory_fact: Builder[MemoryFact]) -> None:
        fact = make_memory_fact()
        disputed = fact.mark_disputed(now=LATER)

        assert disputed.status is MemoryStatus.DISPUTED
        assert not disputed.status.is_retrievable

    def test_mark_disputed_from_unconfirmed(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        fact = make_memory_fact(status=MemoryStatus.UNCONFIRMED)
        disputed = fact.mark_disputed(now=LATER)

        assert disputed.status is MemoryStatus.DISPUTED

    def test_mark_disputed_from_expired_is_refused(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        fact = make_memory_fact(status=MemoryStatus.EXPIRED)
        with pytest.raises(InvariantViolationError):
            fact.mark_disputed(now=LATER)

    def test_mark_expired(self, make_memory_fact: Builder[MemoryFact]) -> None:
        fact = make_memory_fact()
        expired = fact.mark_expired(now=LATER)

        assert expired.status is MemoryStatus.EXPIRED

    def test_only_active_facts_can_expire(self, make_memory_fact: Builder[MemoryFact]) -> None:
        fact = make_memory_fact(status=MemoryStatus.DISPUTED)
        with pytest.raises(InvariantViolationError):
            fact.mark_expired(now=LATER)

    def test_mark_deleted(self, make_memory_fact: Builder[MemoryFact]) -> None:
        fact = make_memory_fact()
        deleted = fact.mark_deleted(now=LATER)

        assert deleted.status is MemoryStatus.DELETED

    def test_a_superseded_fact_cannot_be_deleted(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        fact = make_memory_fact(status=MemoryStatus.SUPERSEDED, superseded_by=uuid4())
        with pytest.raises(InvariantViolationError):
            fact.mark_deleted(now=LATER)

    def test_an_already_deleted_fact_cannot_be_deleted_again(
        self, make_memory_fact: Builder[MemoryFact]
    ) -> None:
        fact = make_memory_fact(status=MemoryStatus.DELETED)
        with pytest.raises(InvariantViolationError):
            fact.mark_deleted(now=LATER)

    @pytest.mark.parametrize(
        "status",
        [
            MemoryStatus.SUPERSEDED,
            MemoryStatus.EXPIRED,
            MemoryStatus.DELETED,
            MemoryStatus.DISPUTED,
            MemoryStatus.UNCONFIRMED,
        ],
    )
    def test_non_active_statuses_are_not_retrievable(self, status: MemoryStatus) -> None:
        assert not status.is_retrievable
