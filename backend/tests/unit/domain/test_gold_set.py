"""Unit tests for GoldPair and GoldSet.

The invariants here all guard the same thing: a gold set that is quietly wrong scores
every run identically and nobody notices, because a wrong number and a right number look
the same on a chart.
"""

from __future__ import annotations

import pytest

from app.domain.enums import QueryClass
from app.domain.errors import InvariantViolationError
from app.domain.evaluation.entities import GoldPair, GoldSet

_SOURCE = "Data Science in the Cloud (O'Reilly, 62 pp)"


#: Distinguishes "no pages given" from "deliberately empty", which is the difference
#: between the default case and the one being rejected.
_DEFAULT_PAGES = frozenset({7, 8})


def _pair(
    pair_id: str = "libraries-01",
    *,
    expected_class: QueryClass = QueryClass.AGGREGATION,
    gold_pages: frozenset[int] = _DEFAULT_PAGES,
    unanswerable: bool = False,
) -> GoldPair:
    return GoldPair(
        id=pair_id,
        question="What Python libraries are used in this book?",
        expected_class=expected_class,
        document="Data Science in the Cloud.pdf",
        gold_pages=frozenset() if unanswerable else gold_pages,
        unanswerable=unanswerable,
    )


class TestGoldPair:
    def test_a_pair_naming_no_pages_is_refused(self) -> None:
        """It scores every retrieval identically, which is worse than a missing pair:
        it counts towards the total and measures nothing."""
        with pytest.raises(InvariantViolationError, match="no gold pages"):
            _pair(gold_pages=frozenset())

    def test_page_numbers_below_one_are_refused(self) -> None:
        """A zero here is almost always an index that was meant to be a page number."""
        with pytest.raises(InvariantViolationError, match="numbered from 1"):
            _pair(gold_pages=frozenset({0, 7}))

    def test_a_blank_question_is_refused(self) -> None:
        with pytest.raises(InvariantViolationError):
            GoldPair(
                id="x",
                question="   ",
                expected_class=QueryClass.DIRECT,
                document="book.pdf",
                gold_pages=frozenset({1}),
            )

    def test_a_pair_names_the_file_rather_than_a_document_id(self) -> None:
        """Document ids are re-minted on every upload. The point of the set is to
        outlive the index it is scoring."""
        assert _pair().document.endswith(".pdf")


class TestUnanswerablePairs:
    def test_an_unanswerable_pair_needs_no_pages(self) -> None:
        """Retrieval finding nothing is the correct outcome, and a set with none of these
        cannot tell a system that abstains from one that never abstains."""
        assert _pair(unanswerable=True).gold_pages == frozenset()

    def test_an_unanswerable_pair_naming_pages_is_refused(self) -> None:
        """It is either answerable or it is not, and a pair claiming both is a labelling
        mistake that would score as a retrieval failure."""
        with pytest.raises(InvariantViolationError, match="unanswerable"):
            GoldPair(
                id="x",
                question="What does chapter 9 say?",
                expected_class=QueryClass.DIRECT,
                document="book.pdf",
                gold_pages=frozenset({3}),
                unanswerable=True,
            )


class TestGoldSet:
    def test_duplicate_ids_are_refused(self) -> None:
        """Scores are reported per pair, and two pairs sharing an id cannot both be read."""
        with pytest.raises(InvariantViolationError, match="Duplicate"):
            GoldSet(pairs=(_pair("a"), _pair("a")), source=_SOURCE)

    def test_an_empty_set_is_refused(self) -> None:
        with pytest.raises(InvariantViolationError, match="measures nothing"):
            GoldSet(pairs=(), source=_SOURCE)

    def test_a_set_must_say_what_it_was_written_against(self) -> None:
        """Against a different file every page number still resolves, to the wrong
        content — the failure is silent and the scores look ordinary."""
        with pytest.raises(InvariantViolationError):
            GoldSet(pairs=(_pair(),), source="  ")

    def test_answerable_excludes_the_pairs_with_no_answer(self) -> None:
        gold_set = GoldSet(pairs=(_pair("a"), _pair("b", unanswerable=True)), source=_SOURCE)

        assert [pair.id for pair in gold_set.answerable] == ["a"]

    def test_pairs_can_be_read_back_by_class(self) -> None:
        gold_set = GoldSet(
            pairs=(
                _pair("a", expected_class=QueryClass.DIRECT),
                _pair("b", expected_class=QueryClass.AGGREGATION),
                _pair("c", expected_class=QueryClass.DIRECT),
            ),
            source=_SOURCE,
        )

        assert [p.id for p in gold_set.by_class(QueryClass.DIRECT)] == ["a", "c"]

    def test_the_set_reports_which_classes_it_covers(self) -> None:
        """An overall number says nothing about the classes the set never asked about."""
        gold_set = GoldSet(
            pairs=(
                _pair("a", expected_class=QueryClass.DIRECT),
                _pair("b", expected_class=QueryClass.VISUAL),
            ),
            source=_SOURCE,
        )

        assert gold_set.classes_covered == frozenset({QueryClass.DIRECT, QueryClass.VISUAL})
        assert len(gold_set.classes_covered) < len(list(QueryClass))
