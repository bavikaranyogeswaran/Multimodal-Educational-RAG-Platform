"""Tests for the DocumentFigure entity — schema and invariants."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.documents.figures import DocumentFigure
from app.domain.enums import ElementType
from app.domain.errors import InvariantViolationError
from app.domain.values import BoundingBox, UntrustedText

_NOW = datetime(2026, 8, 22, tzinfo=UTC)
_BOX = BoundingBox(x0=10.0, y0=20.0, x1=200.0, y1=120.0)


def _figure(**overrides: object) -> DocumentFigure:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "knowledge_base_id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "source_element_id": uuid.uuid4(),
        "page_number": 5,
        "kind": ElementType.FIGURE,
        "bounding_box": _BOX,
        "created_at": _NOW,
    }
    defaults.update(overrides)
    return DocumentFigure(**defaults)  # type: ignore[arg-type]


class TestConstruction:
    def test_a_well_formed_figure_is_accepted(self) -> None:
        fig = _figure()
        assert fig.kind is ElementType.FIGURE
        assert fig.is_described is False

    def test_the_entity_is_frozen(self) -> None:
        with pytest.raises(Exception):
            _figure().page_number = 3  # type: ignore[misc]

    def test_it_reports_its_own_scope(self) -> None:
        user, kb = uuid.uuid4(), uuid.uuid4()
        fig = _figure(user_id=user, knowledge_base_id=kb)
        assert fig.scope.user_id == user
        assert fig.scope.knowledge_base_id == kb

    def test_chart_kind_is_accepted(self) -> None:
        fig = _figure(kind=ElementType.CHART)
        assert fig.kind is ElementType.CHART

    def test_diagram_kind_is_accepted(self) -> None:
        fig = _figure(kind=ElementType.DIAGRAM)
        assert fig.kind is ElementType.DIAGRAM


class TestKindValidation:
    def test_table_kind_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError, match="FIGURE, CHART or DIAGRAM"):
            _figure(kind=ElementType.TABLE)

    def test_paragraph_kind_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError, match="FIGURE, CHART or DIAGRAM"):
            _figure(kind=ElementType.PARAGRAPH)

    def test_formula_kind_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError, match="FIGURE, CHART or DIAGRAM"):
            _figure(kind=ElementType.FORMULA)


class TestConfidence:
    def test_confidence_within_range_is_accepted(self) -> None:
        _figure(confidence=0.85)

    def test_confidence_of_zero_is_accepted(self) -> None:
        _figure(confidence=0.0)

    def test_confidence_of_one_is_accepted(self) -> None:
        _figure(confidence=1.0)

    def test_confidence_above_one_is_refused(self) -> None:
        with pytest.raises(InvariantViolationError):
            _figure(confidence=1.01)

    def test_confidence_below_zero_is_refused(self) -> None:
        with pytest.raises(InvariantViolationError):
            _figure(confidence=-0.1)

    def test_absent_confidence_is_accepted(self) -> None:
        _figure(confidence=None)


class TestCaptionAndNumber:
    def test_caption_is_stored_as_untrusted_text(self) -> None:
        cap = UntrustedText("Figure 3.2: Stress-strain curve")
        fig = _figure(caption=cap)
        assert fig.caption is cap

    def test_number_is_stored_as_written(self) -> None:
        fig = _figure(number="3.2")
        assert fig.number == "3.2"

    def test_both_absent_by_default(self) -> None:
        fig = _figure()
        assert fig.caption is None
        assert fig.number is None


class TestIsDescribed:
    def test_not_described_without_description(self) -> None:
        assert _figure().is_described is False

    def test_described_once_description_is_set(self) -> None:
        assert _figure(description="A stress-strain curve for steel.").is_described is True


class TestChartFields:
    def test_chart_fields_default_to_none(self) -> None:
        fig = _figure(kind=ElementType.CHART)
        assert fig.title is None
        assert fig.chart_type is None
        assert fig.x_axis_label is None
        assert fig.y_axis_label is None

    def test_chart_fields_are_stored(self) -> None:
        fig = _figure(
            kind=ElementType.CHART,
            title="Accuracy over epochs",
            chart_type="line",
            x_axis_label="Epoch",
            y_axis_label="Accuracy",
        )
        assert fig.title == "Accuracy over epochs"
        assert fig.chart_type == "line"
        assert fig.x_axis_label == "Epoch"
        assert fig.y_axis_label == "Accuracy"


class TestDiagramFields:
    def test_diagram_tuples_default_to_empty(self) -> None:
        fig = _figure(kind=ElementType.DIAGRAM)
        assert fig.diagram_labels == ()
        assert fig.components == ()
        assert fig.arrows == ()
        assert fig.visible_relationships == ()

    def test_diagram_fields_are_stored(self) -> None:
        fig = _figure(
            kind=ElementType.DIAGRAM,
            diagram_labels=("Input", "Layer 1", "Output"),
            components=("encoder", "decoder"),
            arrows=("Input → Layer 1", "Layer 1 → Output"),
            visible_relationships=("encoder produces hidden state",),
        )
        assert fig.diagram_labels == ("Input", "Layer 1", "Output")
        assert fig.components == ("encoder", "decoder")
        assert "Input → Layer 1" in fig.arrows
