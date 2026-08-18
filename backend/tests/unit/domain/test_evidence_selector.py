"""Tests for EvidenceSelector.

How many passages reach the model is not a presentation detail. Too few and a comparison
compares one thing against nothing; too many and the answer drifts toward whatever the
surplus happened to say. Both failures read as fluent answers afterwards, and neither shows
up as a retrieval error, so the properties worth pinning here are about counts and the
order the limits win in — not about ranking, which the reranker already settled.

Token counting is a word count. What is under test is where the cut falls, and a fake
counter keeps the arithmetic legible: a budget of twenty tokens means twenty words.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.documents.chunks import Chunk
from app.domain.enums import ChunkType, QueryClass, RetrieverKind
from app.domain.errors import InvariantViolationError
from app.domain.retrieval.entities import Evidence, EvidenceLabel
from app.domain.retrieval.selector import CountRange, EvidenceSelector
from app.domain.values import UntrustedText

_NOW = datetime(2025, 6, 1, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()


def _count_words(text: str) -> int:
    return len(text.split())


def _selector(
    *,
    min_items: int = 1,
    max_items: int = 8,
    margin: float = 0.35,
    budget: int = 10_000,
) -> EvidenceSelector:
    return EvidenceSelector(
        _count_words,
        min_items=min_items,
        max_items=max_items,
        relative_score_margin=margin,
        token_budget=budget,
    )


def _evidence(
    score: float, *, words: int = 5, position: int = 0, stale_label: int | None = None
) -> Evidence:
    return Evidence(
        label=EvidenceLabel(stale_label if stale_label is not None else position + 1),
        chunk=Chunk(
            id=uuid.uuid4(),
            user_id=_USER_ID,
            knowledge_base_id=_KB_ID,
            document_id=uuid.uuid4(),
            chunk_type=ChunkType.TEXT,
            text=UntrustedText(" ".join(f"word{i}" for i in range(words))),
            token_count=words,
            ordinal=position,
            page_start=1,
            page_end=1,
            index_version=1,
            created_at=_NOW,
        ),
        retrievers=frozenset({RetrieverKind.DENSE}),
        rank=position,
        rerank_score=score,
    )


def _candidates(*scores: float, words: int = 5) -> list[Evidence]:
    """Ranked best-first, which is the order the reranker hands over.

    Their labels and ranks are deliberately stale — reversed, as if fusion had numbered
    them and reranking had then reordered them, which is exactly what happens upstream.
    Handing them in already numbered 1..n would make renumbering indistinguishable from
    doing nothing.
    """
    total = len(scores)
    return [
        _evidence(score, words=words, position=total - 1 - i, stale_label=total - i)
        for i, score in enumerate(scores)
    ]


# ---------------------------------------------------------------------------
# The count follows the question
# ---------------------------------------------------------------------------


class TestCountsByQueryClass:
    def test_a_direct_question_is_not_answered_with_five_passages(self) -> None:
        """Given material, the model uses it, so the surplus drags the answer toward
        whatever those passages said."""
        selected = _selector().select(
            _candidates(1.0, 0.99, 0.98, 0.97, 0.96), query_class=QueryClass.DIRECT
        )
        assert len(selected) == 2

    def test_a_comparison_is_not_answered_from_one_source(self) -> None:
        selected = _selector().select(
            _candidates(1.0, 0.99, 0.98, 0.97, 0.96), query_class=QueryClass.COMPARISON
        )
        assert len(selected) >= 2

    def test_a_summary_is_allowed_breadth(self) -> None:
        selected = _selector().select(
            _candidates(*[1.0 - i * 0.01 for i in range(10)]),
            query_class=QueryClass.SUMMARY,
        )
        assert len(selected) > 3

    def test_no_class_exceeds_the_global_ceiling(self) -> None:
        for query_class in QueryClass:
            selected = _selector(max_items=8).select(
                _candidates(*[1.0 - i * 0.001 for i in range(20)]),
                query_class=query_class,
            )
            assert 1 <= len(selected) <= 8, query_class

    def test_the_ceiling_can_be_tightened_by_configuration(self) -> None:
        selected = _selector(max_items=2).select(
            _candidates(*[1.0 - i * 0.001 for i in range(10)]),
            query_class=QueryClass.SUMMARY,
        )
        assert len(selected) == 2

    def test_an_unlisted_class_still_returns_something(self) -> None:
        """A missing range must not fail the query."""
        selector = EvidenceSelector(
            _count_words,
            min_items=1,
            max_items=8,
            relative_score_margin=0.35,
            token_budget=1000,
            ranges={},
        )
        assert selector.select(_candidates(1.0, 0.99), query_class=QueryClass.DIRECT)


# ---------------------------------------------------------------------------
# Which limit wins
# ---------------------------------------------------------------------------


class TestPrecedence:
    def test_a_weak_second_source_is_kept_for_a_comparison(self) -> None:
        """The margin says what the ranking believes; the class minimum says what the
        question requires. Answering a comparison from one source produces a confident
        half-answer, where two lets the model say the sources cover one side."""
        selected = _selector(margin=0.1).select(
            _candidates(1.0, 0.2), query_class=QueryClass.COMPARISON
        )
        assert len(selected) == 2

    def test_the_same_weak_second_is_dropped_for_a_direct_question(self) -> None:
        """Nothing about a direct question requires a second passage, so the margin
        decides and it is far behind."""
        selected = _selector(margin=0.1).select(
            _candidates(1.0, 0.2), query_class=QueryClass.DIRECT
        )
        assert len(selected) == 1

    def test_the_budget_wins_over_the_class_minimum(self) -> None:
        """Passages past the limit are not sent anywhere — the model truncates them from
        the end, silently."""
        selected = _selector(budget=12).select(
            _candidates(1.0, 0.99, 0.98, words=10), query_class=QueryClass.COMPARISON
        )
        assert len(selected) == 1

    def test_one_passage_survives_every_limit(self) -> None:
        """A prompt with no evidence is a question answered from the model's memory."""
        selected = _selector(budget=1, margin=0.0).select(
            _candidates(1.0, words=500), query_class=QueryClass.DIRECT
        )
        assert len(selected) == 1

    def test_a_close_second_is_kept_where_a_distant_one_is_not(self) -> None:
        close = _selector(margin=0.35).select(
            _candidates(1.0, 0.9, 0.1), query_class=QueryClass.EXACT_TERM
        )
        assert len(close) == 2


# ---------------------------------------------------------------------------
# The score margin
# ---------------------------------------------------------------------------


class TestScoreMargin:
    def test_negative_scores_do_not_discard_everything(self) -> None:
        """Cross-encoder scores are not calibrated across queries: a strongly relevant
        pair can score below zero, so the margin is relative to the best one."""
        selected = _selector(margin=0.1).select(
            _candidates(-10.58, -10.6, -11.24), query_class=QueryClass.SUMMARY
        )
        assert len(selected) >= 2

    def test_a_margin_of_zero_keeps_only_the_top_score(self) -> None:
        selected = _selector(margin=0.0).select(
            _candidates(1.0, 0.99), query_class=QueryClass.DIRECT
        )
        assert len(selected) == 1

    def test_unscored_candidates_are_not_filtered_on_score(self) -> None:
        """Nothing to compare against is not the same as scoring badly."""
        candidates = [
            Evidence(
                label=EvidenceLabel(i + 1),
                chunk=_evidence(0.0, position=i).chunk,
                retrievers=frozenset({RetrieverKind.KEYWORD}),
                rank=i,
            )
            for i in range(3)
        ]
        selected = _selector().select(candidates, query_class=QueryClass.SUMMARY)
        assert len(selected) == 3


# ---------------------------------------------------------------------------
# Labelling
# ---------------------------------------------------------------------------


class TestLabelling:
    def test_labels_are_renumbered_from_one(self) -> None:
        """The label is what the model cites, so it must describe the list actually sent
        rather than a position in the list before selection."""
        selected = _selector().select(
            _candidates(1.0, 0.99, 0.98), query_class=QueryClass.SUMMARY
        )
        assert [e.label.number for e in selected] == [1, 2, 3]

    def test_ranks_match_the_position_sent(self) -> None:
        selected = _selector().select(
            _candidates(1.0, 0.99, 0.98), query_class=QueryClass.SUMMARY
        )
        assert [e.rank for e in selected] == [0, 1, 2]

    def test_the_ranking_order_is_not_changed(self) -> None:
        candidates = _candidates(1.0, 0.99, 0.98)
        ids = [c.chunk.id for c in candidates]
        selected = _selector().select(candidates, query_class=QueryClass.SUMMARY)
        assert [e.chunk.id for e in selected] == ids


# ---------------------------------------------------------------------------
# Degenerate input and configuration
# ---------------------------------------------------------------------------


class TestDegenerateInput:
    def test_no_candidates_select_nothing(self) -> None:
        assert _selector().select([], query_class=QueryClass.DIRECT) == []


class TestConfigurationBounds:
    def test_a_ceiling_below_the_floor_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError):
            _selector(min_items=5, max_items=2)

    def test_a_negative_margin_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError):
            _selector(margin=-0.1)

    def test_a_budget_of_zero_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError):
            _selector(budget=0)

    def test_a_range_maximum_below_its_minimum_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError):
            CountRange(3, 1)

    def test_a_range_clamps_into_the_global_bounds(self) -> None:
        clamped = CountRange(3, 8).clamped_to(floor=1, ceiling=2)
        assert (clamped.minimum, clamped.maximum) == (2, 2)
