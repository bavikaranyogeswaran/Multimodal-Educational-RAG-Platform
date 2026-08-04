"""The Knowledge Base entity."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.domain.enums import ExplanationLevel
from app.domain.errors import InvariantViolationError
from app.domain.knowledge_base.entities import KnowledgeBase
from app.domain.scope import ScopeContext

from .conftest import LATER, NOW, Builder


class TestConstruction:
    def test_defaults(self, make_knowledge_base: Builder[KnowledgeBase]) -> None:
        kb = make_knowledge_base()

        assert kb.preferred_language == "en"
        assert kb.explanation_level is ExplanationLevel.INTERMEDIATE
        assert kb.active_index_version == 1
        assert kb.active_graph_version == 1

    def test_graph_extraction_is_off_by_default(
        self, make_knowledge_base: Builder[KnowledgeBase]
    ) -> None:
        """Most questions never touch the graph, and building it is expensive."""
        assert make_knowledge_base().graph_enabled is False

    def test_rejects_a_blank_name(self, make_knowledge_base: Builder[KnowledgeBase]) -> None:
        with pytest.raises(InvariantViolationError, match="name must not be blank"):
            make_knowledge_base(name="   ")

    def test_rejects_an_overlong_name(self, make_knowledge_base: Builder[KnowledgeBase]) -> None:
        with pytest.raises(InvariantViolationError, match="at most 200"):
            make_knowledge_base(name="x" * 201)

    def test_rejects_a_naive_timestamp(self, make_knowledge_base: Builder[KnowledgeBase]) -> None:
        """A naive datetime means a different instant depending on where it is read."""
        with pytest.raises(InvariantViolationError, match="timezone-aware"):
            make_knowledge_base(created_at=datetime(2026, 8, 2, 12, 0))  # noqa: DTZ001

    def test_rejects_an_update_before_creation(
        self, make_knowledge_base: Builder[KnowledgeBase]
    ) -> None:
        with pytest.raises(InvariantViolationError, match="precedes"):
            make_knowledge_base(created_at=LATER, updated_at=NOW)

    def test_rejects_a_non_positive_version(
        self, make_knowledge_base: Builder[KnowledgeBase]
    ) -> None:
        with pytest.raises(InvariantViolationError, match="active_index_version"):
            make_knowledge_base(active_index_version=0)


class TestScope:
    def test_a_knowledge_base_is_its_own_scope(
        self, make_knowledge_base: Builder[KnowledgeBase]
    ) -> None:
        """Nothing downstream should have to pair two loose identifiers correctly."""
        kb = make_knowledge_base()

        assert kb.scope == ScopeContext(user_id=kb.user_id, knowledge_base_id=kb.id)

    def test_scope_uses_the_knowledge_base_id_not_a_separate_field(
        self,
        make_knowledge_base: Builder[KnowledgeBase],
    ) -> None:
        kb = make_knowledge_base()
        assert kb.scope.knowledge_base_id == kb.id


class TestTransitions:
    def test_renaming_returns_a_new_instance(
        self, make_knowledge_base: Builder[KnowledgeBase]
    ) -> None:
        kb = make_knowledge_base(name="Old")
        renamed = kb.renamed("New", now=LATER)

        assert renamed.name == "New"
        assert renamed.updated_at == LATER
        assert kb.name == "Old"

    def test_renaming_trims_whitespace(self, make_knowledge_base: Builder[KnowledgeBase]) -> None:
        assert make_knowledge_base().renamed("  Calculus  ", now=LATER).name == "Calculus"

    def test_renaming_to_blank_is_refused(
        self, make_knowledge_base: Builder[KnowledgeBase]
    ) -> None:
        with pytest.raises(InvariantViolationError):
            make_knowledge_base().renamed("  ", now=LATER)

    def test_enabling_graph_extraction(self, make_knowledge_base: Builder[KnowledgeBase]) -> None:
        kb = make_knowledge_base()
        enabled = kb.with_graph_enabled(enabled=True, now=LATER)

        assert enabled.graph_enabled
        assert not kb.graph_enabled

    def test_disabling_graph_extraction_keeps_the_graph_version(
        self,
        make_knowledge_base: Builder[KnowledgeBase],
    ) -> None:
        """Turning it off stops new extraction; it does not discard what was built."""
        kb = make_knowledge_base(graph_enabled=True, active_graph_version=4)
        disabled = kb.with_graph_enabled(enabled=False, now=LATER)

        assert not disabled.graph_enabled
        assert disabled.active_graph_version == 4

    def test_index_version_advances_by_one(
        self, make_knowledge_base: Builder[KnowledgeBase]
    ) -> None:
        kb = make_knowledge_base(active_index_version=3)
        assert kb.with_next_index_version(now=LATER).active_index_version == 4

    def test_advancing_the_index_leaves_the_graph_version_alone(
        self,
        make_knowledge_base: Builder[KnowledgeBase],
    ) -> None:
        """The two rebuild independently; coupling them would force needless work."""
        kb = make_knowledge_base(active_index_version=1, active_graph_version=7)
        advanced = kb.with_next_index_version(now=LATER)

        assert advanced.active_index_version == 2
        assert advanced.active_graph_version == 7


class TestExamCountdown:
    def test_no_exam_date_means_no_countdown(
        self, make_knowledge_base: Builder[KnowledgeBase]
    ) -> None:
        assert make_knowledge_base().days_until_exam(date(2026, 8, 2)) is None

    def test_counts_days_remaining(self, make_knowledge_base: Builder[KnowledgeBase]) -> None:
        kb = make_knowledge_base(exam_date=date(2026, 9, 2))
        assert kb.days_until_exam(date(2026, 8, 2)) == 31

    def test_a_past_exam_counts_negative(self, make_knowledge_base: Builder[KnowledgeBase]) -> None:
        """Study planning has to notice a date that has already gone by."""
        kb = make_knowledge_base(exam_date=date(2026, 7, 1))
        assert kb.days_until_exam(date(2026, 8, 2)) == -32

    def test_the_exam_day_itself_is_zero(self, make_knowledge_base: Builder[KnowledgeBase]) -> None:
        kb = make_knowledge_base(exam_date=date(2026, 8, 2))
        assert kb.days_until_exam(date(2026, 8, 2)) == 0


def test_time_is_supplied_rather_than_read(make_knowledge_base: Builder[KnowledgeBase]) -> None:
    """The domain has no clock of its own.

    Every transition takes the current time as an argument, so behaviour is reproducible
    and a test never has to freeze a global.
    """
    fixed = datetime(2030, 1, 1, tzinfo=UTC)
    assert make_knowledge_base().renamed("Anything", now=fixed).updated_at == fixed
