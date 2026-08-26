"""Tests for DocumentSelector."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from app.application.queries.document_selection import (
    DocumentScore,
    DocumentSelection,
    DocumentSelector,
)
from app.application.queries.sub_question_pipeline import SubQuestionResult
from app.domain.retrieval.decomposition import SubQuestion


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sub_question(sq_id: str = "Q1") -> SubQuestion:
    return SubQuestion(id=sq_id, text=f"Question {sq_id}?")


def _evidence(doc_id: uuid.UUID, *, rerank_score: float | None = 1.0) -> MagicMock:
    ev = MagicMock()
    ev.document_id = doc_id
    ev.rerank_score = rerank_score
    return ev


def _result(
    sq_id: str,
    evidence_items: list[MagicMock],
) -> SubQuestionResult:
    return SubQuestionResult(
        sub_question=_sub_question(sq_id),
        evidence=evidence_items,
        standalone_query=f"standalone {sq_id}",
    )


# ---------------------------------------------------------------------------
# constructor
# ---------------------------------------------------------------------------


class TestDocumentSelectorConstructor:
    def test_max_documents_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            DocumentSelector(max_documents=0)

    def test_max_documents_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            DocumentSelector(max_documents=-1)

    def test_valid_construction(self) -> None:
        sel = DocumentSelector(max_documents=5)
        assert sel is not None


# ---------------------------------------------------------------------------
# empty / trivial cases
# ---------------------------------------------------------------------------


class TestDocumentSelectorEdgeCases:
    def test_empty_results_returns_empty_selection(self) -> None:
        sel = DocumentSelector(max_documents=5)
        result = sel.select([])
        assert result.selected_ids == frozenset()
        assert result.scores == ()

    def test_results_with_no_evidence_returns_empty_selection(self) -> None:
        sel = DocumentSelector(max_documents=5)
        result = sel.select([_result("Q1", [])])
        assert result.selected_ids == frozenset()

    def test_single_doc_single_sub_question(self) -> None:
        doc_id = uuid.uuid4()
        sel = DocumentSelector(max_documents=5)
        result = sel.select([_result("Q1", [_evidence(doc_id, rerank_score=0.8)])])
        assert result.selected_ids == {doc_id}
        assert len(result.scores) == 1
        assert result.scores[0].sub_questions_covered == 1
        assert result.scores[0].total_rerank_score == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


class TestDocumentSelectorScoring:
    def test_document_covering_more_sub_questions_ranked_first(self) -> None:
        doc_a = uuid.uuid4()
        doc_b = uuid.uuid4()
        # doc_a appears in Q1 and Q2; doc_b only in Q1
        results = [
            _result("Q1", [_evidence(doc_a, rerank_score=1.0), _evidence(doc_b, rerank_score=5.0)]),
            _result("Q2", [_evidence(doc_a, rerank_score=1.0)]),
        ]
        sel = DocumentSelector(max_documents=5)
        selection = sel.select(results)
        assert selection.scores[0].document_id == doc_a
        assert selection.scores[0].sub_questions_covered == 2

    def test_tie_broken_by_total_rerank_score(self) -> None:
        doc_a = uuid.uuid4()
        doc_b = uuid.uuid4()
        # Both cover Q1 only; doc_b has higher rerank score
        results = [
            _result("Q1", [
                _evidence(doc_a, rerank_score=1.0),
                _evidence(doc_b, rerank_score=3.0),
            ]),
        ]
        sel = DocumentSelector(max_documents=5)
        selection = sel.select(results)
        assert selection.scores[0].document_id == doc_b

    def test_rerank_score_none_contributes_zero(self) -> None:
        doc_id = uuid.uuid4()
        sel = DocumentSelector(max_documents=5)
        result = sel.select([_result("Q1", [_evidence(doc_id, rerank_score=None)])])
        assert result.scores[0].total_rerank_score == pytest.approx(0.0)

    def test_total_rerank_score_sums_all_chunks(self) -> None:
        doc_id = uuid.uuid4()
        results = [
            _result("Q1", [_evidence(doc_id, rerank_score=1.5)]),
            _result("Q2", [_evidence(doc_id, rerank_score=2.5)]),
        ]
        sel = DocumentSelector(max_documents=5)
        selection = sel.select(results)
        assert selection.scores[0].total_rerank_score == pytest.approx(4.0)

    def test_same_document_in_multiple_sub_questions_counted_once_per_sub_question(self) -> None:
        doc_id = uuid.uuid4()
        # doc appears twice in Q1 (two chunks) and once in Q2
        results = [
            _result("Q1", [_evidence(doc_id), _evidence(doc_id)]),
            _result("Q2", [_evidence(doc_id)]),
        ]
        sel = DocumentSelector(max_documents=5)
        selection = sel.select(results)
        # sub_questions_covered counts unique sub-question IDs, so 2
        assert selection.scores[0].sub_questions_covered == 2


# ---------------------------------------------------------------------------
# cap enforcement
# ---------------------------------------------------------------------------


class TestDocumentSelectorCap:
    def test_max_documents_caps_selected_ids(self) -> None:
        docs = [uuid.uuid4() for _ in range(5)]
        results = [_result("Q1", [_evidence(doc_id) for doc_id in docs])]
        sel = DocumentSelector(max_documents=3)
        selection = sel.select(results)
        assert len(selection.selected_ids) == 3

    def test_full_ranking_in_scores_even_when_capped(self) -> None:
        docs = [uuid.uuid4() for _ in range(5)]
        results = [_result("Q1", [_evidence(doc_id) for doc_id in docs])]
        sel = DocumentSelector(max_documents=2)
        selection = sel.select(results)
        assert len(selection.scores) == 5  # full ranking always returned

    def test_cap_equal_to_candidate_count_selects_all(self) -> None:
        docs = [uuid.uuid4() for _ in range(3)]
        results = [_result("Q1", [_evidence(doc_id) for doc_id in docs])]
        sel = DocumentSelector(max_documents=3)
        selection = sel.select(results)
        assert selection.selected_ids == frozenset(docs)

    def test_selected_ids_are_highest_scored_documents(self) -> None:
        doc_broad = uuid.uuid4()  # covers Q1 and Q2 — will score highest
        doc_narrow = uuid.uuid4()  # covers Q1 only
        doc_other = uuid.uuid4()   # covers Q2 only, lower rerank
        results = [
            _result("Q1", [
                _evidence(doc_broad, rerank_score=1.0),
                _evidence(doc_narrow, rerank_score=0.5),
            ]),
            _result("Q2", [
                _evidence(doc_broad, rerank_score=1.0),
                _evidence(doc_other, rerank_score=0.1),
            ]),
        ]
        sel = DocumentSelector(max_documents=2)
        selection = sel.select(results)
        # doc_broad covers 2 sub-questions → always selected
        assert doc_broad in selection.selected_ids
        # doc_narrow and doc_other each cover 1; narrow has higher rerank (0.5 vs 0.1)
        assert doc_narrow in selection.selected_ids
        assert doc_other not in selection.selected_ids
