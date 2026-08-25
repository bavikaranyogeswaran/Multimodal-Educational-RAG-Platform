"""Unit tests for the retrieval metrics.

Every expected value here is worked out by hand and written as the arithmetic that
produced it, not as a decimal. A metric checked against a number somebody once observed
is a metric that can only ever confirm it has not changed.
"""

from __future__ import annotations

from math import log2

import pytest

from app.domain.errors import InvariantViolationError
from app.domain.evaluation.metrics import (
    ndcg_at_k,
    page_recall_at_k,
    phrases_found,
    precision_at_k,
    reciprocal_rank,
    score,
)

# A run of five passages against an answer living on pages 4, 5 and 6. Positions 1 and 4
# are relevant; the rest are not.
_RUN = [[4], [11], [12], [5, 6], [30]]
_GOLD = [4, 5, 6]


class TestPageRecall:
    def test_reaching_every_gold_page_scores_one(self) -> None:
        assert page_recall_at_k([[4, 5, 6]], _GOLD, k=1) == 1.0

    def test_reaching_none_of_them_scores_zero(self) -> None:
        assert page_recall_at_k([[40], [41]], _GOLD, k=2) == 0.0

    def test_pages_are_counted_across_the_whole_window(self) -> None:
        """One passage covering three gold pages has found the whole answer; three
        passages covering one page between them have not."""
        assert page_recall_at_k(_RUN, _GOLD, k=5) == 3 / 3

    def test_a_truncated_window_loses_the_pages_below_it(self) -> None:
        """Only page 4 is reached in the top three, so a third of the answer."""
        assert page_recall_at_k(_RUN, _GOLD, k=3) == 1 / 3

    def test_the_same_page_twice_does_not_count_twice(self) -> None:
        assert page_recall_at_k([[4], [4], [4]], _GOLD, k=3) == 1 / 3

    def test_pages_outside_the_gold_set_do_not_help(self) -> None:
        assert page_recall_at_k([[4, 99, 100]], _GOLD, k=1) == 1 / 3

    def test_no_gold_pages_is_refused_rather_than_scored(self) -> None:
        """Dividing by nothing would report 0.0, which reads as a failed retrieval
        rather than as a question that could not be scored."""
        with pytest.raises(InvariantViolationError):
            page_recall_at_k(_RUN, [], k=5)


class TestPrecision:
    def test_counts_relevant_passages_over_the_window(self) -> None:
        """Positions 1 and 4 touch a gold page, out of five slots."""
        assert precision_at_k(_RUN, _GOLD, k=5) == 2 / 5

    def test_divides_by_k_rather_than_by_what_came_back(self) -> None:
        """Retrieval asked for five slots and filled two. The empty ones are part of the
        result, and dividing by two would score a half-empty run as perfect."""
        assert precision_at_k([[4], [5]], _GOLD, k=5) == 2 / 5

    def test_an_empty_run_scores_zero(self) -> None:
        assert precision_at_k([], _GOLD, k=5) == 0.0

    def test_a_window_smaller_than_the_run_ignores_the_tail(self) -> None:
        assert precision_at_k(_RUN, _GOLD, k=2) == 1 / 2


class TestReciprocalRank:
    def test_a_relevant_passage_at_the_top_scores_one(self) -> None:
        assert reciprocal_rank([[4], [99]], _GOLD) == 1.0

    def test_ranks_count_from_one(self) -> None:
        """Fourth place scores a quarter, not a third."""
        assert reciprocal_rank([[99], [98], [97], [5]], _GOLD) == 1 / 4

    def test_nothing_relevant_scores_zero(self) -> None:
        assert reciprocal_rank([[99], [98]], _GOLD) == 0.0

    def test_only_the_first_relevant_passage_counts(self) -> None:
        """This is what makes it different from precision: a run that is right once at
        the top and wrong everywhere else is a good run by this measure."""
        assert reciprocal_rank([[4], [5], [6]], _GOLD) == reciprocal_rank([[4]], _GOLD)


class TestNdcg:
    def test_all_relevant_scores_one(self) -> None:
        assert ndcg_at_k([[4], [5], [6]], _GOLD, k=3) == 1.0

    def test_nothing_relevant_scores_zero(self) -> None:
        assert ndcg_at_k([[99], [98]], _GOLD, k=2) == 0.0

    def test_relevant_last_scores_worse_than_relevant_first(self) -> None:
        first = ndcg_at_k([[4], [99], [98]], _GOLD, k=3)
        last = ndcg_at_k([[99], [98], [4]], _GOLD, k=3)
        assert first == 1.0
        assert last < first

    def test_the_discount_is_log2_of_the_position_plus_one(self) -> None:
        """Relevant at positions 1 and 4 of five. The ideal ordering puts both first."""
        actual = 1 / log2(2) + 1 / log2(5)
        ideal = 1 / log2(2) + 1 / log2(3)
        assert ndcg_at_k(_RUN, _GOLD, k=5) == pytest.approx(actual / ideal)

    def test_ordering_is_what_it_measures(self) -> None:
        """The one thing recall and precision cannot see: these two runs return the same
        passages and score identically on both."""
        good = [[4], [99], [98], [97]]
        bad = [[99], [98], [97], [4]]
        assert precision_at_k(good, _GOLD, k=4) == precision_at_k(bad, _GOLD, k=4)
        assert page_recall_at_k(good, _GOLD, k=4) == page_recall_at_k(bad, _GOLD, k=4)
        assert ndcg_at_k(good, _GOLD, k=4) > ndcg_at_k(bad, _GOLD, k=4)


class TestPhrases:
    def test_no_required_phrases_is_not_a_failure(self) -> None:
        """Most pairs name none. Scoring them zero would drag every average down for a
        check that was never asked for."""
        assert phrases_found(["anything at all"], []) == 1.0

    def test_a_phrase_present_anywhere_in_the_retrieved_text_counts(self) -> None:
        assert phrases_found(["first passage", "holds Spyder here"], ["spyder"]) == 1.0

    def test_matching_ignores_case(self) -> None:
        assert phrases_found(["Azure Machine Learning Studio"], ["azure machine"]) == 1.0

    def test_partial_credit_when_some_phrases_are_missing(self) -> None:
        assert phrases_found(["only Jupyter here"], ["jupyter", "spyder"]) == 1 / 2

    def test_a_phrase_may_be_carried_by_any_passage(self) -> None:
        """The question is whether the model saw it, not which passage delivered it."""
        assert phrases_found(["jupyter", "spyder"], ["jupyter", "spyder"]) == 1.0


class TestScore:
    def test_reports_every_metric_for_one_run(self) -> None:
        result = score(_RUN, _GOLD, k=5)

        assert result.page_recall == 3 / 3
        assert result.precision == 2 / 5
        assert result.reciprocal_rank == 1.0
        assert result.returned == 5

    def test_carries_the_window_it_was_scored_over(self) -> None:
        """A precision of 0.2 over five slots and over fifty are different results, and
        the number alone cannot say which."""
        assert score(_RUN, _GOLD, k=3).k == 3

    def test_counts_what_came_back_not_what_was_asked_for(self) -> None:
        assert score([[4]], _GOLD, k=10).returned == 1

    def test_phrases_are_scored_from_the_retrieved_text(self) -> None:
        result = score(
            _RUN,
            _GOLD,
            k=5,
            retrieved_text=["a passage naming Spyder", "another"],
            must_contain=["spyder", "ipython"],
        )

        assert result.phrases == 1 / 2
