"""Rendering a structured table into the forms the rest of the system needs.

Four of them, for four different readers. JSON is what a caller reconstructs the grid
from. Markdown is what goes in front of a model, because a model reads a pipe table far
better than it reads a paragraph of numbers. HTML is for a viewer that wants to lay the
table out. Prose is what gets embedded, and it is the one whose shape is a decision
rather than a format.

The prose form names a column on every row it appears in. That costs repetition, and it
buys two things. A search for "accuracy on run 2" matches a line that contains both the
word and the number, rather than a line of bare figures whose meaning lives in a header
several lines above. And because every line stands on its own, a table too large to keep
whole can be cut between lines without leaving rows whose columns nobody names — the one
split that would otherwise produce confidently mislabelled evidence.

Everything here is a pure function of the table. Nothing reads a clock, a file or a
model, so the rendered text for a given grid is the same every time it is produced.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any

from app.domain.documents.tables import DocumentTable


@dataclass(frozen=True, slots=True)
class TableRenderings:
    """Every serialised form of one table, produced together."""

    table_json: dict[str, Any]
    markdown: str
    html: str
    embedding_text: str


def _labelled(header: str, unit: str | None) -> str:
    """A column name with its unit, where it has one."""
    return f"{header} ({unit})" if unit else header


def _unit_at(table: DocumentTable, index: int) -> str | None:
    if index >= len(table.units):
        return None
    return table.units[index]


def to_json_payload(table: DocumentTable) -> dict[str, Any]:
    """The grid as data, for a caller that wants to rebuild it rather than read it."""
    return {
        "number": table.number,
        "caption": table.caption.value if table.caption is not None else None,
        "headers": list(table.headers),
        "units": [_unit_at(table, index) for index in range(len(table.headers))],
        "rows": [list(row) for row in table.rows],
    }


def to_markdown(table: DocumentTable) -> str:
    """A pipe table, with any caption on the line above it.

    Cell contents have their pipes escaped. An unescaped pipe inside a cell would end
    that cell early and shift every value after it one column left, which is the same
    silent corruption the row-alignment invariant exists to prevent.
    """

    def cell(value: str) -> str:
        return value.replace("|", r"\|").replace("\n", " ")

    header_row = " | ".join(
        cell(_labelled(header, _unit_at(table, index)))
        for index, header in enumerate(table.headers)
    )
    rule = " | ".join("---" for _ in table.headers)

    lines = [f"| {header_row} |", f"| {rule} |"]
    lines.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in table.rows)

    body = "\n".join(lines)
    if table.caption is not None:
        return f"{table.caption.value}\n\n{body}"
    return body


def to_html(table: DocumentTable) -> str:
    """A table element, with every value escaped.

    The cells came out of a file a student uploaded, so anything in them that looks like
    markup is content that happens to look like markup. Escaping is what keeps a cell
    reading `<script>` from becoming one wherever this is rendered.
    """
    parts: list[str] = ["<table>"]

    if table.caption is not None:
        parts.append(f"<caption>{html.escape(table.caption.value)}</caption>")

    heads = "".join(
        f"<th>{html.escape(_labelled(header, _unit_at(table, index)))}</th>"
        for index, header in enumerate(table.headers)
    )
    parts.append(f"<thead><tr>{heads}</tr></thead>")

    if table.rows:
        body = "".join(
            "<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in row) + "</tr>"
            for row in table.rows
        )
        parts.append(f"<tbody>{body}</tbody>")

    parts.append("</table>")
    return "".join(parts)


def to_embedding_text(table: DocumentTable) -> str:
    """The table as prose, one self-describing line per row.

    A row renders as its column names paired with its values, so the line carries its own
    meaning wherever it ends up. Empty cells are dropped rather than rendered as a column
    name followed by nothing, which reads as a measurement that was taken and came back
    blank instead of one that was never there.
    """
    lines: list[str] = []

    if table.caption is not None:
        lines.append(table.caption.value.strip())

    for row in table.rows:
        pairs: list[str] = []
        for index, value in enumerate(row):
            text = value.strip()
            if not text:
                continue
            header = table.headers[index]
            unit = _unit_at(table, index)
            pairs.append(f"{header} {text} {unit}" if unit else f"{header} {text}")
        if pairs:
            lines.append(", ".join(pairs) + ".")

    # A table with a caption and no readable rows still says what it was about, and that
    # is worth retrieving — a student asking about it should find the place it sits even
    # when nothing could be read out of it.
    return "\n".join(lines).strip()


def render(table: DocumentTable) -> TableRenderings:
    """Every serialised form at once."""
    return TableRenderings(
        table_json=to_json_payload(table),
        markdown=to_markdown(table),
        html=to_html(table),
        embedding_text=to_embedding_text(table),
    )
