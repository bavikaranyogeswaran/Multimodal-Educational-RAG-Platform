"""The parse report's own logic, which will be read as evidence and can lie quietly.

This script exists to decide whether the parser is doing the right thing on a real
document, so a wrong reading here is worse than no reading: it is a measurement that
looks like a measurement. The first version of the column check asked whether reading
order ever jumped back up the page, which is what column detection looks like in most
layouts and not what it looks like in this one — the resolver reads band by band, so a
two-column page never jumps upward. It reported no columns on a page that has two, and
nothing about the output said so.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

from app.domain.documents.entities import DocumentElement
from app.domain.enums import ElementType, ProcessingMethod
from app.domain.values import BoundingBox, UntrustedText

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "inspect_parse.py"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    """Load the script by path — it lives outside the importable package."""
    spec = importlib.util.spec_from_file_location("inspect_parse", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["inspect_parse"] = module
    spec.loader.exec_module(module)
    return module


def _element(box: BoundingBox | None, *, order: int = 0) -> DocumentElement:
    return DocumentElement(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        page_number=1,
        element_type=ElementType.PARAGRAPH,
        text=UntrustedText("some text"),
        reading_order=order,
        processing_method=ProcessingMethod.NATIVE_TEXT,
        created_at=datetime(2025, 6, 1, tzinfo=UTC),
        bounding_box=box,
    )


def test_script_exists() -> None:
    assert SCRIPT.is_file()


class TestColumnDetection:
    """Coordinates are PDF coordinates: y increases upward, so y1 is the top edge."""

    def test_a_step_to_the_right_at_the_same_height_is_a_column_break(
        self, script: ModuleType
    ) -> None:
        elements = [
            _element(BoundingBox(72, 618, 234, 698), order=0),
            _element(BoundingBox(320, 618, 461, 698), order=1),
        ]
        assert script._reads_as_columns(elements)

    def test_paragraphs_stacked_down_one_column_are_not(self, script: ModuleType) -> None:
        elements = [
            _element(BoundingBox(72, 618, 461, 698), order=0),
            _element(BoundingBox(72, 500, 461, 600), order=1),
        ]
        assert not script._reads_as_columns(elements)

    def test_a_narrower_paragraph_below_a_wider_one_is_not(self, script: ModuleType) -> None:
        """An indented block or a short last line sits inside the measure above it, and
        calling that a column would report columns on nearly every page."""
        elements = [
            _element(BoundingBox(72, 618, 461, 698), order=0),
            _element(BoundingBox(300, 500, 461, 600), order=1),
        ]
        assert not script._reads_as_columns(elements)

    def test_a_right_column_starting_lower_than_its_neighbour_still_counts(
        self, script: ModuleType
    ) -> None:
        """Columns rarely begin level. A heading above the left column pushes its first
        paragraph down, so the right one starts higher and overlaps only partly — asking
        that the later block start at or above the earlier one would miss the page."""
        elements = [
            _element(BoundingBox(72, 618, 234, 698), order=0),
            _element(BoundingBox(320, 560, 461, 650), order=1),
        ]
        assert script._reads_as_columns(elements)

    def test_a_block_to_the_right_but_wholly_below_is_the_next_band(
        self, script: ModuleType
    ) -> None:
        """Reading order runs band by band, so something that shares no height with what
        preceded it is the next band down, whatever its horizontal position."""
        elements = [
            _element(BoundingBox(72, 618, 234, 698), order=0),
            _element(BoundingBox(320, 400, 461, 500), order=1),
        ]
        assert not script._reads_as_columns(elements)

    def test_elements_without_boxes_are_skipped(self, script: ModuleType) -> None:
        assert not script._reads_as_columns([_element(None), _element(None)])

    def test_a_single_element_page_has_no_columns(self, script: ModuleType) -> None:
        assert not script._reads_as_columns([_element(BoundingBox(72, 618, 234, 698))])

    def test_no_elements_is_not_an_error(self, script: ModuleType) -> None:
        assert not script._reads_as_columns([])


class TestPageRanges:
    """Scanned pages arrive as runs, and a list of 300 numbers is unreadable."""

    def test_a_run_becomes_a_range(self, script: ModuleType) -> None:
        assert script._compress([4, 5, 6, 7]) == "4-7"

    def test_isolated_pages_stay_separate(self, script: ModuleType) -> None:
        assert script._compress([2, 9, 14]) == "2, 9, 14"

    def test_runs_and_singles_mix(self, script: ModuleType) -> None:
        assert script._compress([1, 2, 3, 8, 11, 12]) == "1-3, 8, 11-12"

    def test_one_page_is_itself(self, script: ModuleType) -> None:
        assert script._compress([5]) == "5"

    def test_nothing_renders_as_nothing(self, script: ModuleType) -> None:
        assert script._compress([]) == ""
