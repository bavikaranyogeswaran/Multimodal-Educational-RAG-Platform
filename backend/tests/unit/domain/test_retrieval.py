"""Evidence, labels, citations and the retrieval plan.

The tests that matter most here are the ones about citation resolution: a fabricated
citation must be impossible to pass off as genuine, including when it names a chunk that
really exists somewhere else.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.documents.chunks import Chunk
from app.domain.enums import EarlyExitPath, QueryClass, RetrieverKind
from app.domain.errors import InvariantViolationError, NotFoundError
from app.domain.retrieval.entities import (
    Citation,
    Evidence,
    EvidenceLabel,
    EvidenceSet,
    RetrievalFilters,
    RetrievalPlan,
)
from app.domain.values import BoundingBox

from .conftest import Builder


class TestEvidenceLabel:
    def test_renders_as_the_model_sees_it(self) -> None:
        assert str(EvidenceLabel(1)) == "S1"
        assert EvidenceLabel(4).bracketed == "[S4]"

    @pytest.mark.parametrize("raw", ["S1", "[S1]", " S1 ", "[S1] "])
    def test_parses_the_forms_a_model_produces(self, raw: str) -> None:
        assert EvidenceLabel.parse(raw) == EvidenceLabel(1)

    @pytest.mark.parametrize("raw", ["", "S", "S0", "X1", "1", "S-1", "SS1", "S1a"])
    def test_rejects_malformed_labels(self, raw: str) -> None:
        with pytest.raises(InvariantViolationError):
            EvidenceLabel.parse(raw)

    def test_try_parse_reports_rather_than_raises(self) -> None:
        """Parsing model output expects malformed labels; they are data, not bugs."""
        assert EvidenceLabel.try_parse("nonsense") is None
        assert EvidenceLabel.try_parse("S2") == EvidenceLabel(2)

    def test_labels_sort_numerically(self) -> None:
        labels = sorted([EvidenceLabel(10), EvidenceLabel(2), EvidenceLabel(1)])
        assert [label.number for label in labels] == [1, 2, 10]

    def test_rejects_zero(self) -> None:
        with pytest.raises(InvariantViolationError):
            EvidenceLabel(0)


class TestEvidence:
    def test_must_record_where_it_came_from(self, make_evidence: Builder[Evidence]) -> None:
        """Evidence that arrived from nowhere cannot be explained or reproduced."""
        with pytest.raises(InvariantViolationError, match="at least one retriever"):
            make_evidence(retrievers=frozenset())

    def test_agreement_between_retrievers_is_visible(
        self, make_evidence: Builder[Evidence]
    ) -> None:
        single = make_evidence(retrievers=frozenset({RetrieverKind.DENSE}))
        both = make_evidence(retrievers=frozenset({RetrieverKind.DENSE, RetrieverKind.KEYWORD}))

        assert not single.found_by_multiple_retrievers
        assert both.found_by_multiple_retrievers

    def test_becomes_a_citation_carrying_its_location(
        self, make_evidence: Builder[Evidence]
    ) -> None:
        evidence = make_evidence(
            chunk_overrides={"page_start": 67, "bounding_box": BoundingBox(10, 20, 110, 60)}
        )

        citation = evidence.to_citation(order=0)

        assert citation.label == evidence.label
        assert citation.chunk_id == evidence.chunk.id
        assert citation.page_number == 67
        assert citation.is_navigable

    def test_a_citation_without_a_box_still_opens_the_page(
        self, make_evidence: Builder[Evidence]
    ) -> None:
        citation = make_evidence(chunk_overrides={"bounding_box": None}).to_citation(order=0)

        assert not citation.is_navigable
        assert citation.page_number > 0


class TestEvidenceSet:
    def test_labels_are_assigned_positionally(self, make_evidence: Builder[Evidence]) -> None:
        evidence_set = EvidenceSet.labelled([make_evidence() for _ in range(3)])

        assert [str(label) for label in evidence_set.labels] == ["S1", "S2", "S3"]

    def test_reports_its_size_and_token_cost(self, make_evidence: Builder[Evidence]) -> None:
        evidence_set = EvidenceSet.labelled(
            [
                make_evidence(chunk_overrides={"token_count": 100}),
                make_evidence(chunk_overrides={"token_count": 250}),
            ]
        )

        assert len(evidence_set) == 2
        assert evidence_set.total_tokens == 350

    def test_reports_which_documents_contributed(self, make_evidence: Builder[Evidence]) -> None:
        """Source coverage is measured from this."""
        first, second = uuid4(), uuid4()
        evidence_set = EvidenceSet.labelled(
            [
                make_evidence(chunk_overrides={"document_id": first}),
                make_evidence(chunk_overrides={"document_id": second}),
                make_evidence(chunk_overrides={"document_id": first}),
            ]
        )

        assert evidence_set.document_ids == frozenset({first, second})

    def test_an_empty_set_is_falsy_and_has_no_scope(self) -> None:
        empty = EvidenceSet.empty()

        assert not empty
        assert len(empty) == 0
        assert empty.scope is None

    def test_duplicate_labels_are_refused(self, make_evidence: Builder[Evidence]) -> None:
        with pytest.raises(InvariantViolationError, match="unique"):
            EvidenceSet(
                (
                    make_evidence(label=EvidenceLabel(1)),
                    make_evidence(label=EvidenceLabel(1)),
                )
            )


@pytest.mark.security
class TestCitationsCannotBeFabricated:
    def test_resolving_a_supplied_label_succeeds(self, make_evidence: Builder[Evidence]) -> None:
        evidence_set = EvidenceSet.labelled([make_evidence() for _ in range(3)])

        assert evidence_set.require(EvidenceLabel(2)).label == EvidenceLabel(2)

    def test_a_label_beyond_the_set_is_refused(self, make_evidence: Builder[Evidence]) -> None:
        """Citing a fourth source when three were supplied is an invention."""
        evidence_set = EvidenceSet.labelled([make_evidence() for _ in range(3)])

        with pytest.raises(NotFoundError, match="was not supplied"):
            evidence_set.require(EvidenceLabel(4))

    def test_a_real_chunk_that_was_not_in_context_is_still_refused(
        self, make_evidence: Builder[Evidence], make_chunk: Builder[Chunk]
    ) -> None:
        """The check is against what the model was given, not against what exists.

        A chunk can be perfectly real, belong to the right student and the right Knowledge
        Base, and still not have been supplied for this question. Citing it is a
        fabrication, and resolving against the database rather than the supplied set would
        wave it through.
        """
        supplied = EvidenceSet.labelled([make_evidence(), make_evidence()])
        elsewhere = make_chunk()

        assert not supplied.contains(EvidenceLabel(3))
        assert all(item.chunk.id != elsewhere.id for item in supplied)

    def test_an_evidence_set_may_not_span_two_knowledge_bases(
        self, make_evidence: Builder[Evidence]
    ) -> None:
        """Mixed evidence is a leak that has already happened by the time anyone looks."""
        intruder = uuid4()

        with pytest.raises(InvariantViolationError, match="more than one scope"):
            EvidenceSet.labelled(
                [
                    make_evidence(),
                    make_evidence(chunk_overrides={"knowledge_base_id": intruder}),
                ]
            )

    def test_a_set_from_one_scope_reports_that_scope(
        self, make_evidence: Builder[Evidence]
    ) -> None:
        evidence_set = EvidenceSet.labelled([make_evidence(), make_evidence()])

        assert evidence_set.scope is not None
        assert evidence_set.scope == evidence_set.items[0].chunk.scope


class TestRetrievalFilters:
    def test_an_unset_filter_narrows_nothing(self) -> None:
        assert not RetrievalFilters().is_narrowed

    def test_naming_a_chapter_narrows(self) -> None:
        assert RetrievalFilters(chapter="4").is_narrowed

    def test_a_selected_object_is_recognised(self) -> None:
        assert RetrievalFilters(table_id=uuid4()).targets_a_specific_object
        assert RetrievalFilters(figure_id=uuid4()).targets_a_specific_object
        assert not RetrievalFilters(chapter="4").targets_a_specific_object

    def test_rejects_a_page_number_below_one(self) -> None:
        with pytest.raises(InvariantViolationError, match="page_number"):
            RetrievalFilters(page_number=0)


class TestRetrievalPlan:
    def test_a_direct_question_searches_broadly_and_expands(self) -> None:
        plan = RetrievalPlan.for_query(QueryClass.DIRECT)

        assert plan.retrievers == frozenset({RetrieverKind.DENSE, RetrieverKind.KEYWORD})
        assert plan.expand_queries
        assert not plan.consult_graph
        assert not plan.decompose
        assert plan.runs_broad_retrieval

    def test_an_exact_term_is_never_paraphrased(self) -> None:
        """Expanding a quotation moves the query away from the passage containing it."""
        plan = RetrievalPlan.for_query(QueryClass.EXACT_TERM)

        assert not plan.expand_queries
        assert plan.early_exit is EarlyExitPath.EXACT_LOOKUP
        assert RetrieverKind.KEYWORD in plan.retrievers

    def test_a_selected_table_takes_the_shortcut(self) -> None:
        plan = RetrievalPlan.for_query(QueryClass.TABLE, filters=RetrievalFilters(table_id=uuid4()))

        assert plan.early_exit is EarlyExitPath.TABLE_LOOKUP
        assert not plan.expand_queries
        assert not plan.runs_broad_retrieval
        assert not plan.consult_graph

    def test_a_table_question_without_a_selection_searches_normally(self) -> None:
        """A shortcut is only a shortcut when the object it depends on was chosen."""
        plan = RetrievalPlan.for_query(QueryClass.TABLE)

        assert plan.early_exit is None
        assert plan.runs_broad_retrieval

    def test_a_selected_figure_takes_the_visual_shortcut(self) -> None:
        plan = RetrievalPlan.for_query(
            QueryClass.VISUAL, filters=RetrievalFilters(figure_id=uuid4())
        )

        assert plan.early_exit is EarlyExitPath.VISUAL_LOOKUP
        assert RetrieverKind.VISUAL in plan.retrievers

    def test_graph_supplements_rather_than_replaces(self) -> None:
        plan = RetrievalPlan.for_query(QueryClass.RELATIONSHIP, graph_available=True)

        assert plan.consult_graph
        assert RetrieverKind.GRAPH in plan.retrievers
        assert RetrieverKind.DENSE in plan.retrievers
        assert RetrieverKind.KEYWORD in plan.retrievers

    def test_no_graph_is_consulted_when_the_knowledge_base_has_none(self) -> None:
        """Graph extraction is opt-in, so most Knowledge Bases have nothing to traverse."""
        plan = RetrievalPlan.for_query(QueryClass.RELATIONSHIP, graph_available=False)

        assert not plan.consult_graph
        assert RetrieverKind.GRAPH not in plan.retrievers
        assert plan.retrievers

    def test_a_direct_question_never_consults_the_graph_even_when_available(self) -> None:
        assert not RetrievalPlan.for_query(QueryClass.DIRECT, graph_available=True).consult_graph

    @pytest.mark.parametrize(
        "query_class",
        [
            QueryClass.MULTI_HOP,
            QueryClass.MULTI_DOCUMENT,
            QueryClass.AGGREGATION,
            QueryClass.COMPARISON,
        ],
    )
    def test_classes_that_decompose(self, query_class: QueryClass) -> None:
        assert RetrievalPlan.for_query(query_class).decompose

    def test_the_plan_records_the_class_it_came_from(self) -> None:
        """So a decision can be compared against its outcome afterwards."""
        assert RetrievalPlan.for_query(QueryClass.SUMMARY).query_class is QueryClass.SUMMARY


class TestRetrievalPlanInvariants:
    def test_a_plan_must_run_something(self) -> None:
        with pytest.raises(InvariantViolationError, match="at least one retriever"):
            RetrievalPlan(
                query_class=QueryClass.DIRECT,
                retrievers=frozenset(),
                expand_queries=True,
                consult_graph=False,
                decompose=False,
            )

    def test_consulting_the_graph_requires_the_graph_retriever(self) -> None:
        with pytest.raises(InvariantViolationError, match="graph retriever is not in the plan"):
            RetrievalPlan(
                query_class=QueryClass.RELATIONSHIP,
                retrievers=frozenset({RetrieverKind.DENSE}),
                expand_queries=True,
                consult_graph=True,
                decompose=False,
            )

    def test_the_graph_retriever_requires_consulting_the_graph(self) -> None:
        with pytest.raises(InvariantViolationError, match="consult_graph is not set"):
            RetrievalPlan(
                query_class=QueryClass.RELATIONSHIP,
                retrievers=frozenset({RetrieverKind.DENSE, RetrieverKind.GRAPH}),
                expand_queries=True,
                consult_graph=False,
                decompose=False,
            )

    def test_a_shortcut_and_query_expansion_are_contradictory(self) -> None:
        """The target is already resolved; expanding cannot improve on it."""
        with pytest.raises(InvariantViolationError, match="add latency"):
            RetrievalPlan(
                query_class=QueryClass.TABLE,
                retrievers=frozenset({RetrieverKind.TABLE}),
                expand_queries=True,
                consult_graph=False,
                decompose=False,
                early_exit=EarlyExitPath.TABLE_LOOKUP,
            )


def test_citation_ordering_starts_at_zero(make_evidence: Builder[Evidence]) -> None:
    citation = make_evidence().to_citation(order=0)
    assert citation.citation_order == 0


def test_a_citation_needs_a_real_page(make_evidence: Builder[Evidence]) -> None:
    with pytest.raises(InvariantViolationError, match="page_number"):
        Citation(
            label=EvidenceLabel(1),
            chunk_id=uuid4(),
            document_id=uuid4(),
            page_number=0,
            citation_order=0,
        )
