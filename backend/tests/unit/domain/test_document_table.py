"""Tests for the table entity — the invariants that keep a value under the right column."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.documents.tables import DocumentTable
from app.domain.errors import InvariantViolationError
from app.domain.values import BoundingBox, UntrustedText

_NOW = datetime(2026, 8, 22, tzinfo=UTC)
_BOX = BoundingBox(x0=10.0, y0=20.0, x1=200.0, y1=120.0)


def _table(**overrides: object) -> DocumentTable:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "knowledge_base_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "source_element_id": uuid.uuid4(),
        "page_number": 12,
        "headers": ("Metal", "Density"),
        "rows": (("Aluminium", "2.70"), ("Iron", "7.87")),
        "bounding_box": _BOX,
        "created_at": _NOW,
    }
    defaults.update(overrides)
    return DocumentTable(**defaults)  # type: ignore[arg-type]


class TestConstruction:
    def test_a_well_formed_table_is_accepted(self) -> None:
        table = _table()
        assert table.column_count == 2
        assert table.row_count == 2

    def test_the_entity_is_frozen(self) -> None:
        with pytest.raises(Exception):
            _table().page_number = 3  # type: ignore[misc]

    def test_it_reports_its_own_scope(self) -> None:
        user, kb = uuid.uuid4(), uuid.uuid4()
        table = _table(user_id=user, knowledge_base_id=kb)
        assert table.scope.user_id == user
        assert table.scope.knowledge_base_id == kb


class TestRowAlignment:
    def test_a_row_narrower_than_the_headers_is_refused(self) -> None:
        # The failure this prevents is silent: a short row shifts every value after the
        # gap one column left, so the table answers confidently with the wrong figure.
        with pytest.raises(InvariantViolationError, match="does not line up"):
            _table(rows=(("Aluminium",),))

    def test_a_row_wider_than_the_headers_is_refused(self) -> None:
        with pytest.raises(InvariantViolationError, match="does not line up"):
            _table(rows=(("Aluminium", "2.70", "extra"),))

    def test_the_offending_row_is_named(self) -> None:
        with pytest.raises(InvariantViolationError, match="row 1"):
            _table(rows=(("Aluminium", "2.70"), ("Iron",)))

    def test_a_table_with_no_rows_is_allowed(self) -> None:
        # A detected region that yielded nothing still marks a place on the page a
        # student can point at.
        table = _table(rows=())
        assert table.is_empty is True


class TestHeaders:
    def test_a_table_without_headers_is_refused(self) -> None:
        with pytest.raises(InvariantViolationError, match="must name its columns"):
            _table(headers=(), rows=())

    def test_column_returns_every_value_beneath_a_name(self) -> None:
        assert _table().column("Density") == ("2.70", "7.87")

    def test_asking_for_a_column_that_does_not_exist_raises(self) -> None:
        # Returning empty here would read as "this column is blank" when it means
        # "you asked for a column that is not in this table".
        with pytest.raises(InvariantViolationError, match="no column named"):
            _table().column("Melting point")


class TestUnits:
    def test_units_may_be_omitted_entirely(self) -> None:
        assert _table().unit_for("Density") is None

    def test_units_must_line_up_with_headers_when_given(self) -> None:
        with pytest.raises(InvariantViolationError, match="units must line up"):
            _table(units=("g/cm3",))

    def test_a_unit_is_found_by_column_name(self) -> None:
        table = _table(units=(None, "g/cm3"))
        assert table.unit_for("Density") == "g/cm3"
        assert table.unit_for("Metal") is None

    def test_an_unknown_column_has_no_unit_rather_than_raising(self) -> None:
        # Unlike `column`, this answers a yes/no question, and "no unit" is a truthful
        # answer for a column that is not there.
        assert _table(units=(None, "g/cm3")).unit_for("Melting point") is None


class TestValidation:
    def test_a_page_number_below_one_is_refused(self) -> None:
        with pytest.raises(InvariantViolationError):
            _table(page_number=0)

    def test_a_naive_timestamp_is_refused(self) -> None:
        with pytest.raises(InvariantViolationError):
            _table(created_at=datetime(2026, 8, 22))  # noqa: DTZ001

    def test_a_confidence_outside_zero_to_one_is_refused(self) -> None:
        with pytest.raises(InvariantViolationError):
            _table(confidence=1.4)

    def test_confidence_may_be_absent(self) -> None:
        assert _table().confidence is None


class TestCaption:
    def test_a_caption_is_untrusted_text(self) -> None:
        table = _table(caption=UntrustedText("Table 4.2: Properties of common metals"))
        assert table.caption is not None
        # The safeguard is that the content does not come back from `str`, so a caption
        # interpolated into a prompt by accident cannot deliver instructions.
        assert "Properties" not in str(table.caption)
        assert "Properties" in table.caption.value

    def test_a_caption_may_be_absent(self) -> None:
        assert _table().caption is None
