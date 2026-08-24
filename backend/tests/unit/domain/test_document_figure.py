"""Tests for the DocumentFigure entity — schema and invariants."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.documents.figures import DocumentFigure, to_embedding_text
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


class TestToEmbeddingText:
    """The prose a figure is retrieved by.

    A figure region carries no text of its own, so this is the only thing that makes one
    findable. What matters is that each source of meaning reaches the output and that a
    figure the vision model never saw still returns something.
    """

    def test_caption_alone_is_enough_to_be_retrievable(self) -> None:
        """A figure nothing could be read out of still names what it was about."""
        fig = _figure(caption=UntrustedText("Model training workflow"))
        assert to_embedding_text(fig) == "Model training workflow"

    def test_number_precedes_the_caption(self) -> None:
        fig = _figure(number="Figure 4", caption=UntrustedText("Model training workflow"))
        assert to_embedding_text(fig) == "Figure 4 Model training workflow"

    def test_a_number_the_caption_already_carries_is_not_repeated(self) -> None:
        """Captions are usually read off the page complete with their own label."""
        fig = _figure(number="1", caption=UntrustedText("Figure 1. Azure ML Studio"))
        assert to_embedding_text(fig) == "Figure 1. Azure ML Studio"

    def test_a_number_with_no_caption_still_labels_the_figure(self) -> None:
        assert to_embedding_text(_figure(number="Figure 9")) == "Figure 9"

    def test_description_and_ocr_text_both_reach_the_output(self) -> None:
        fig = _figure(
            caption=UntrustedText("Training workflow"),
            description="A four-stage pipeline from data input to evaluation.",
            ocr_text="Data input Transformations Model Definition Training",
        )
        rendered = to_embedding_text(fig)
        assert "four-stage pipeline" in rendered
        assert "Model Definition" in rendered

    def test_chart_axes_and_trend_are_included(self) -> None:
        fig = _figure(
            kind=ElementType.CHART,
            chart_type="line",
            x_axis_label="epoch",
            y_axis_label="accuracy",
            units_label="percent",
            visible_trend="Accuracy rises steeply then plateaus.",
        )
        rendered = to_embedding_text(fig)
        assert "line chart." in rendered
        assert "x axis epoch, y axis accuracy, units percent." in rendered
        assert "plateaus" in rendered

    def test_diagram_components_and_arrows_are_included(self) -> None:
        fig = _figure(
            kind=ElementType.DIAGRAM,
            components=("encoder", "decoder"),
            arrows=("Input -> Layer 1",),
        )
        rendered = to_embedding_text(fig)
        assert "Components: encoder, decoder." in rendered
        assert "Connections: Input -> Layer 1." in rendered

    def test_absent_fields_leave_no_empty_headings(self) -> None:
        """A figure the vision model never reached must not render blank labels."""
        rendered = to_embedding_text(_figure(caption=UntrustedText("Just a caption")))
        assert "Components" not in rendered
        assert "chart" not in rendered
        assert rendered.count("\n") == 0

    def test_a_figure_with_nothing_known_renders_empty(self) -> None:
        """Callers use the empty string to decide there is nothing worth chunking."""
        assert to_embedding_text(_figure()) == ""

    def test_blank_caption_does_not_produce_a_stray_line(self) -> None:
        assert to_embedding_text(_figure(caption=UntrustedText("   "))) == ""
