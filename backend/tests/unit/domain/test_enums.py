"""Enum completeness and the behaviour attached to members.

Membership counts are asserted because a silently missing member is the kind of omission
that surfaces much later as a query class nothing routes, or a status nothing handles.
"""

from __future__ import annotations

import pytest

from app.domain.enums import (
    CoverageStatus,
    DataBoundary,
    DocumentStatus,
    JobPriority,
    MemoryProvenance,
    MemoryStatus,
    ModelTask,
    QueryClass,
    RelationshipType,
    RequirementLevel,
    ValidationDecision,
)


class TestCompleteness:
    def test_thirteen_query_classes(self) -> None:
        assert len(QueryClass) == 13

    def test_ten_model_tasks(self) -> None:
        assert len(ModelTask) == 10

    def test_nine_relationship_types(self) -> None:
        assert len(RelationshipType) == 9

    def test_six_memory_statuses(self) -> None:
        assert len(MemoryStatus) == 6


class TestDocumentStatus:
    def test_only_completed_is_retrievable(self) -> None:
        retrievable = [s for s in DocumentStatus if s.is_retrievable]
        assert retrievable == [DocumentStatus.COMPLETED]

    def test_deleting_is_not_retrievable(self) -> None:
        """Retrieval stops the moment deletion begins, not when it finishes."""
        assert not DocumentStatus.DELETING.is_retrievable

    def test_terminal_states(self) -> None:
        assert DocumentStatus.COMPLETED.is_terminal
        assert DocumentStatus.FAILED.is_terminal
        assert not DocumentStatus.PROCESSING.is_terminal


class TestOrdering:
    def test_interactive_work_outranks_background(self) -> None:
        assert JobPriority.INTERACTIVE > JobPriority.NORMAL > JobPriority.BACKGROUND

    def test_priorities_sort_highest_first_when_reversed(self) -> None:
        ordered = sorted(JobPriority, reverse=True)
        assert ordered[0] is JobPriority.INTERACTIVE

    def test_critical_requirements_outrank_the_rest(self) -> None:
        assert RequirementLevel.CRITICAL > RequirementLevel.REQUIRED
        assert RequirementLevel.REQUIRED > RequirementLevel.PREFERRED

    def test_a_correction_outranks_an_assistant_guess(self) -> None:
        assert MemoryProvenance.USER_CORRECTION > MemoryProvenance.APPLICATION_EVENT
        assert MemoryProvenance.APPLICATION_EVENT > MemoryProvenance.USER_STATEMENT
        assert MemoryProvenance.USER_STATEMENT > MemoryProvenance.ASSISTANT_INFERENCE


class TestQueryClassRouting:
    @pytest.mark.parametrize(
        "query_class",
        [
            QueryClass.MULTI_DOCUMENT,
            QueryClass.MULTI_HOP,
            QueryClass.AGGREGATION,
            QueryClass.COMPARISON,
        ],
    )
    def test_classes_that_decompose(self, query_class: QueryClass) -> None:
        assert query_class.needs_decomposition

    def test_a_direct_question_does_not_decompose(self) -> None:
        assert not QueryClass.DIRECT.needs_decomposition

    def test_graph_serves_relationship_shaped_questions_only(self) -> None:
        using_graph = {q for q in QueryClass if q.benefits_from_graph}

        assert using_graph == {
            QueryClass.RELATIONSHIP,
            QueryClass.PREREQUISITE,
            QueryClass.CONCEPT_MAP,
        }
        assert not QueryClass.DIRECT.benefits_from_graph

    def test_exact_and_selected_queries_are_never_expanded(self) -> None:
        """Paraphrasing a quotation or an identifier moves the query away from the answer."""
        assert QueryClass.EXACT_TERM.forbids_expansion
        assert QueryClass.TABLE.forbids_expansion
        assert QueryClass.VISUAL.forbids_expansion
        assert not QueryClass.DIRECT.forbids_expansion


class TestValidationOutcomes:
    def test_an_abstention_is_returnable(self) -> None:
        """Saying there is not enough evidence is a correct answer, not a failure."""
        assert ValidationDecision.INSUFFICIENT_EVIDENCE.is_returnable

    def test_a_rejection_is_not_returnable(self) -> None:
        assert not ValidationDecision.REJECTED.is_returnable
        assert not ValidationDecision.REPAIRABLE.is_returnable

    def test_conflicting_coverage_does_not_trigger_more_retrieval(self) -> None:
        """More searching will not resolve sources that genuinely disagree.

        The disagreement is the finding, and it gets reported rather than searched away.
        """
        assert not CoverageStatus.CONFLICTING.needs_another_round
        assert CoverageStatus.UNSUPPORTED.needs_another_round
        assert CoverageStatus.PARTIALLY_SUPPORTED.needs_another_round
        assert not CoverageStatus.SUPPORTED.needs_another_round


class TestMemoryAndPrivacy:
    def test_only_active_memory_is_retrievable(self) -> None:
        retrievable = [s for s in MemoryStatus if s.is_retrievable]
        assert retrievable == [MemoryStatus.ACTIVE]

    def test_deleted_memory_is_never_retrievable(self) -> None:
        assert not MemoryStatus.DELETED.is_retrievable
        assert not MemoryStatus.SUPERSEDED.is_retrievable

    @pytest.mark.security
    def test_only_local_providers_accept_private_content(self) -> None:
        assert DataBoundary.LOCAL.accepts_private_content
        assert not DataBoundary.THIRD_PARTY.accepts_private_content


def test_members_are_strings_carrying_their_own_value() -> None:
    """Storage and serialisation rely on this; a plain Enum would not behave so.

    Asserted through `str()` and `.value` rather than `==` against a literal, because a
    member whose name and value differ makes the direct comparison unprovable to a type
    checker even though it holds at runtime.
    """
    assert isinstance(DocumentStatus.COMPLETED, str)
    assert str(DocumentStatus.COMPLETED) == "COMPLETED"
    assert str(QueryClass.MULTI_HOP) == "MULTI_HOP"

    # The only member whose stored value deliberately differs from its name.
    assert DataBoundary.LOCAL.value == "local"
    assert f"{DataBoundary.LOCAL}" == "local"


def test_visual_questions_are_the_only_task_needing_an_image() -> None:
    needing_images = [t for t in ModelTask if t.requires_image_input]
    assert needing_images == [ModelTask.VISUAL_QUESTION]
