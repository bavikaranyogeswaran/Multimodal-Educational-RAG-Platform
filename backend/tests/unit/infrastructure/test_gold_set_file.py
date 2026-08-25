"""Unit tests for reading a gold set off disk.

A malformed gold set does not fail, it scores — and a wrong number looks exactly like a
right one. Everything here is about failing at load rather than at the chart.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.enums import QueryClass
from app.domain.errors import InvariantViolationError
from app.infrastructure.evaluation.gold_set_file import load_gold_set

#: The set the project actually maintains, checked as data rather than mocked.
_SHIPPED = (
    Path(__file__).parents[3] / "evaluation" / "gold" / "data-science-in-the-cloud.json"
)


def _write(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "gold.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _valid_pair(**overrides: object) -> dict[str, object]:
    pair = {
        "id": "studio-what-is",
        "question": "What is Azure ML Studio?",
        "expected_class": "DIRECT",
        "document": "book.pdf",
        "gold_pages": [9],
    }
    pair.update(overrides)
    return pair


class TestLoading:
    def test_reads_pairs_into_entities(self, tmp_path: Path) -> None:
        path = _write(tmp_path, {"source": "a book", "pairs": [_valid_pair()]})

        gold = load_gold_set(path)

        assert gold.source == "a book"
        assert gold.pairs[0].expected_class is QueryClass.DIRECT
        assert gold.pairs[0].gold_pages == frozenset({9})

    def test_optional_fields_default_rather_than_failing(self, tmp_path: Path) -> None:
        """Most pairs name no phrases and no note; requiring them would make the file
        tedious enough that people stop adding pairs."""
        path = _write(tmp_path, {"source": "a book", "pairs": [_valid_pair()]})

        pair = load_gold_set(path).pairs[0]

        assert pair.must_contain == ()
        assert pair.note == ""
        assert pair.unanswerable is False

    def test_an_unanswerable_pair_loads_without_pages(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            {
                "source": "a book",
                "pairs": [_valid_pair(gold_pages=[], unanswerable=True)],
            },
        )

        assert load_gold_set(path).pairs[0].unanswerable is True


class TestRejection:
    def test_invalid_json_names_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / "gold.json"
        path.write_text("{not json", encoding="utf-8")

        with pytest.raises(InvariantViolationError, match=r"gold\.json"):
            load_gold_set(path)

    def test_a_missing_source_is_refused(self, tmp_path: Path) -> None:
        """Against a different book every page number still resolves, to the wrong
        content, and the scores look ordinary."""
        path = _write(tmp_path, {"pairs": [_valid_pair()]})

        with pytest.raises(InvariantViolationError, match="source"):
            load_gold_set(path)

    def test_an_unknown_query_class_is_refused(self, tmp_path: Path) -> None:
        """Dropping the pair instead would take the class coverage count with it, and
        the set would quietly stop covering what it claims to."""
        path = _write(
            tmp_path,
            {"source": "a book", "pairs": [_valid_pair(expected_class="PROCEDURE")]},
        )

        with pytest.raises(InvariantViolationError, match="unknown query class"):
            load_gold_set(path)

    def test_the_failing_pair_is_named(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            {"source": "a book", "pairs": [_valid_pair(expected_class="NONSENSE")]},
        )

        with pytest.raises(InvariantViolationError, match="studio-what-is"):
            load_gold_set(path)


class TestTheShippedSet:
    """The maintained set is data, and data can be wrong without anything failing."""

    def test_it_loads(self) -> None:
        assert load_gold_set(_SHIPPED).pairs

    def test_every_page_is_inside_the_book(self) -> None:
        """The source names 62 pages. A page number past the end is a labelling slip
        that scores as a retrieval failure for ever after."""
        gold = load_gold_set(_SHIPPED)

        for pair in gold.answerable:
            assert max(pair.gold_pages) <= 62, pair.id

    def test_it_contains_a_question_the_material_does_not_answer(self) -> None:
        """Without one the set cannot tell a system that abstains properly from one that
        never abstains, and every change looks like an improvement."""
        gold = load_gold_set(_SHIPPED)

        assert len(gold.pairs) > len(gold.answerable)

    def test_every_pair_explains_its_labelling(self) -> None:
        """The note is for whoever disagrees later, which is who this file is for."""
        for pair in load_gold_set(_SHIPPED).pairs:
            assert pair.note.strip(), pair.id
