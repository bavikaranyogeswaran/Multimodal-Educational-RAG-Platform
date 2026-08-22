"""Tests for the four serialised forms of a table.

The prose form carries the load: it is what gets embedded, and its shape is a decision
rather than a format. The property that matters most is that a line means something on
its own, because a table too large to keep whole gets cut between lines.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from app.domain.documents.table_render import (
    render,
    to_embedding_text,
    to_html,
    to_json_payload,
    to_markdown,
)
from app.domain.documents.tables import DocumentTable
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


class TestEmbeddingText:
    def test_every_row_names_its_own_columns(self) -> None:
        # The property the whole format exists for: a line cut away from the rest still
        # says what its numbers mean.
        text = to_embedding_text(_table())
        assert "Metal Aluminium, Density 2.70." in text
        assert "Metal Iron, Density 7.87." in text

    def test_each_row_is_its_own_line(self) -> None:
        # So that splitting an oversized table on line boundaries cannot orphan a row
        # from the headers that give it meaning.
        lines = to_embedding_text(_table()).splitlines()
        assert len(lines) == 2

    def test_every_line_stands_alone_after_a_split(self) -> None:
        text = to_embedding_text(_table(units=(None, "g/cm3")))
        for line in text.splitlines():
            assert "Metal" in line
            assert "Density" in line

    def test_units_travel_with_their_values(self) -> None:
        text = to_embedding_text(_table(units=(None, "g/cm3")))
        assert "Density 2.70 g/cm3" in text

    def test_the_caption_leads_the_text(self) -> None:
        text = to_embedding_text(_table(caption=UntrustedText("Table 4.2: Properties of metals")))
        assert text.startswith("Table 4.2: Properties of metals")

    def test_an_empty_cell_is_dropped_rather_than_named(self) -> None:
        # "Density" followed by nothing reads as a measurement that came back blank
        # rather than one that was never taken.
        text = to_embedding_text(_table(rows=(("Aluminium", ""),)))
        assert "Density" not in text
        assert "Metal Aluminium." in text

    def test_a_row_with_nothing_in_it_produces_no_line(self) -> None:
        text = to_embedding_text(_table(rows=(("", ""), ("Iron", "7.87"))))
        assert len(text.splitlines()) == 1

    def test_a_table_with_a_caption_and_no_rows_still_says_what_it_was_about(self) -> None:
        text = to_embedding_text(_table(rows=(), caption=UntrustedText("Table 1: Accuracy by run")))
        assert "Accuracy by run" in text

    def test_a_table_with_nothing_readable_renders_empty(self) -> None:
        assert to_embedding_text(_table(rows=())) == ""


class TestMarkdown:
    def test_it_renders_a_pipe_table(self) -> None:
        markdown = to_markdown(_table())
        assert "| Metal | Density |" in markdown
        assert "| --- | --- |" in markdown
        assert "| Aluminium | 2.70 |" in markdown

    def test_units_appear_in_the_header(self) -> None:
        assert "| Metal | Density (g/cm3) |" in to_markdown(_table(units=(None, "g/cm3")))

    def test_a_pipe_inside_a_cell_is_escaped(self) -> None:
        # Unescaped, it would end the cell early and shift every later value one column
        # left — the same silent corruption the row-alignment invariant prevents.
        markdown = to_markdown(_table(rows=(("A|B", "2.70"),)))
        assert r"A\|B" in markdown

    def test_a_line_break_inside_a_cell_does_not_break_the_row(self) -> None:
        markdown = to_markdown(_table(rows=(("Tensile\nstrength", "410"),)))
        assert "Tensile strength" in markdown
        assert len(markdown.splitlines()) == 3

    def test_the_caption_sits_above_the_table(self) -> None:
        markdown = to_markdown(_table(caption=UntrustedText("Table 1: Metals")))
        assert markdown.splitlines()[0] == "Table 1: Metals"


class TestHtml:
    def test_it_renders_a_table_element(self) -> None:
        markup = to_html(_table())
        assert markup.startswith("<table>")
        assert markup.endswith("</table>")
        assert "<th>Metal</th>" in markup

    def test_rows_become_table_rows(self) -> None:
        assert "<td>Aluminium</td><td>2.70</td>" in to_html(_table())

    def test_markup_in_a_cell_is_escaped(self) -> None:
        # The cells came out of a student's file, so anything that looks like markup is
        # content that happens to look like markup.
        markup = to_html(_table(rows=(("<script>alert(1)</script>", "2.70"),)))
        assert "<script>" not in markup
        assert "&lt;script&gt;" in markup

    def test_markup_in_a_caption_is_escaped(self) -> None:
        markup = to_html(_table(caption=UntrustedText("<img src=x onerror=1>")))
        assert "<img" not in markup

    def test_a_caption_becomes_a_caption_element(self) -> None:
        assert "<caption>Table 1</caption>" in to_html(_table(caption=UntrustedText("Table 1")))

    def test_a_table_with_no_rows_omits_the_body(self) -> None:
        assert "<tbody>" not in to_html(_table(rows=()))


class TestJsonPayload:
    def test_it_carries_the_grid(self) -> None:
        payload = to_json_payload(_table())
        assert payload["headers"] == ["Metal", "Density"]
        assert payload["rows"] == [["Aluminium", "2.70"], ["Iron", "7.87"]]

    def test_units_are_padded_to_the_column_count(self) -> None:
        # So a caller can index units by column without a length check.
        payload = to_json_payload(_table())
        assert payload["units"] == [None, None]

    def test_it_survives_a_json_round_trip(self) -> None:
        payload = to_json_payload(_table(units=(None, "g/cm3")))
        assert json.loads(json.dumps(payload)) == payload

    def test_a_missing_caption_is_null_rather_than_absent(self) -> None:
        assert to_json_payload(_table())["caption"] is None


class TestRenderAll:
    def test_it_produces_every_form_at_once(self) -> None:
        rendering = render(_table())
        assert rendering.markdown
        assert rendering.html
        assert rendering.embedding_text
        assert rendering.table_json["headers"] == ["Metal", "Density"]

    def test_rendering_is_deterministic(self) -> None:
        # Nothing here reads a clock, a file or a model, so the same grid renders the
        # same way every time — which is what lets a stored vector keep meaning.
        table = _table(units=(None, "g/cm3"), caption=UntrustedText("Table 1"))
        assert render(table) == render(table)


class TestAttachingRenderings:
    def test_a_fresh_table_is_not_yet_rendered(self) -> None:
        assert _table().is_rendered is False

    def test_attaching_them_reports_rendered(self) -> None:
        table = _table().with_renderings(
            table_json="{}", markdown="m", html="<table></table>", embedding_text="t"
        )
        assert table.is_rendered is True

    def test_attaching_returns_a_new_table_and_leaves_the_original(self) -> None:
        original = _table()
        attached = original.with_renderings(
            table_json="{}", markdown="m", html="<table></table>", embedding_text="t"
        )
        assert original.embedding_text is None
        assert attached.embedding_text == "t"

    def test_the_grid_survives_attaching(self) -> None:
        attached = _table().with_renderings(
            table_json="{}", markdown="m", html="<table></table>", embedding_text="t"
        )
        assert attached.rows == (("Aluminium", "2.70"), ("Iron", "7.87"))
