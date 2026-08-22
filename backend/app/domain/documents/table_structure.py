"""Turning a grid of cells into named columns, units and data rows.

Table detection hands over a rectangle of strings and no opinion about what any of them
mean. Deciding which row names the columns, whether a second row carries units rather
than data, and how to square off rows that came back ragged is what stands between a
grid and something that can answer a question.

Every rule here is a guess about a document that cannot be asked. They are written to
fail towards keeping data rather than towards a tidy answer: a row that might be a
header and might be data stays data, because losing a row of measurements is a worse
outcome than an ugly column name.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

# A unit written after the column it belongs to: "Mass (kg)", "Speed [m/s]".
# The separator forms are the two that appear in typeset tables; a comma is deliberately
# not among them, because "Population, 2019" is a qualifier rather than a unit and there
# is no way to tell the two apart from punctuation alone.
_TRAILING_UNIT = re.compile(r"^(?P<name>.*?)\s*[(\[](?P<unit>[^)\]]{1,12})[)\]]\s*$")

# What a number looks like in a table cell, allowing thousands separators, a leading
# sign, a decimal part, a percentage, and the comparison prefixes measurements carry.
_NUMERIC = re.compile(
    r"""^\s*
    (?:[<>~≈±]|\+/-)?\s*
    [-+]?
    \d{1,3}(?:,\d{3})*(?:\.\d+)?
    |^\s*[-+]?\d*\.?\d+
    """,
    re.VERBOSE,
)

# Longest a cell can be and still read as a unit rather than a value. Units are terse by
# convention — "kg", "m/s²", "% of GDP" is already unusual — while a data cell that is
# not a number tends to be a word or a phrase.
_MAX_UNIT_LENGTH = 12


@dataclass(frozen=True, slots=True)
class TableStructure:
    """The outcome of reading a grid: column names, their units, and the rows beneath."""

    headers: tuple[str, ...]
    units: tuple[str | None, ...]
    rows: tuple[tuple[str, ...], ...]

    # True when the grid arrived with rows of differing lengths and had to be squared
    # off. Worth surfacing rather than swallowing: a ragged table is one whose detection
    # was imperfect, and how much to trust its values follows from that.
    was_ragged: bool = False

    # True when no row read as a header and the first row was taken as one because
    # something has to name the columns. The names are then real cell values, which is
    # wrong but recoverable, where leaving the columns anonymous is neither.
    header_assumed: bool = False


def _clean(cell: str | None) -> str:
    """Normalise one cell: no surrounding space, no interior line breaks.

    Cells wrap inside their borders, so a single value arrives split across lines. Joining
    with a space restores the phrase; leaving the break in would put a newline in the
    middle of a column name.
    """
    if cell is None:
        return ""
    return " ".join(cell.split())


def _is_numeric(cell: str) -> bool:
    return bool(cell) and bool(_NUMERIC.match(cell))


def _split_unit(header: str) -> tuple[str, str | None]:
    """Separate a trailing parenthesised unit from the column name it follows."""
    match = _TRAILING_UNIT.match(header)
    if not match:
        return header, None

    name = match.group("name").strip()
    unit = match.group("unit").strip()

    # A parenthesised phrase with no name in front of it is the name, not a unit —
    # "(estimated)" as a whole column heading has nothing it could be a unit for.
    if not name or not unit:
        return header, None

    return name, unit


def _holds_data(row: Sequence[str]) -> bool:
    """Whether a row carries measurements, which makes it data rather than column names.

    This is the one signal strong enough to act on alone. Column names are words; a row
    with a number in it is holding a value, and spending it as a header would delete a
    row of the table.
    """
    return any(_is_numeric(cell) for cell in row if cell)


def _has_data_below(below: Sequence[Sequence[str]]) -> bool:
    """Whether anything under a candidate header row reads as a measurement.

    Used to tell a confirmed header from an assumed one. Words above numbers is a header
    on the evidence; words above more words is a header on convention alone.
    """
    return any(_holds_data(row) for row in below)


def _looks_like_units(row: Sequence[str], below: Sequence[Sequence[str]]) -> bool:
    """Whether a row holds units for the row above rather than the first data row.

    Requires the row to be terse, free of numbers, and followed by something numeric —
    a units row with no measurements under it is just a second header, and treating it
    as units would discard a row of content.
    """
    filled = [cell for cell in row if cell]
    if not filled:
        return False

    if any(len(cell) > _MAX_UNIT_LENGTH for cell in filled):
        return False

    if any(_is_numeric(cell) for cell in filled):
        return False

    return any(_is_numeric(cell) for later in below for cell in later if cell)


def _square(rows: Sequence[Sequence[str]], width: int) -> tuple[tuple[tuple[str, ...], ...], bool]:
    """Force every row to the table's width, reporting whether anything had to move.

    Short rows are padded on the right and long ones truncated. Both are lossy guesses;
    the alternative is discarding the row, which loses more.
    """
    ragged = False
    squared: list[tuple[str, ...]] = []

    for row in rows:
        cells = list(row)
        if len(cells) != width:
            ragged = True
        if len(cells) < width:
            cells.extend([""] * (width - len(cells)))
        squared.append(tuple(cells[:width]))

    return tuple(squared), ragged


def resolve_table_structure(grid: Sequence[Sequence[str | None]]) -> TableStructure | None:
    """Read a raw cell grid into headers, units and data rows.

    Returns None when there is nothing to read — an empty grid, or one whose every cell
    is blank. A detected region that holds no text is a detection error rather than an
    empty table, and inventing a single unnamed column for it would put a table into the
    index that the document does not contain.
    """
    cleaned = [[_clean(cell) for cell in row] for row in grid]
    populated = [row for row in cleaned if any(row)]

    if not populated:
        return None

    width = max(len(row) for row in populated)
    squared, ragged = _square(populated, width)

    first, rest = squared[0], squared[1:]

    # Three cases, and only the middle one is certain. A first row holding numbers is
    # data, so the table is left headerless and its columns are named by position — the
    # alternative deletes a row of measurements to obtain column names that are
    # themselves measurements. A first row of words above numbers is a header on the
    # evidence. A first row of words above more words is a header by convention only,
    # which is usually right for a glossary and is flagged either way.
    if _holds_data(first):
        header_cells: tuple[str, ...] = ("",) * width
        body = squared
        header_assumed = True
    else:
        header_cells = first
        body = rest
        header_assumed = not _has_data_below(rest)

    units: list[str | None] = [None] * width

    # A dedicated units row is only considered under a header that was actually read.
    # Where the columns were named by position the first row is already data, and taking
    # the next one as units would discard a second row with it.
    if header_cells != ("",) * width and body and _looks_like_units(body[0], body[1:]):
        units = [cell or None for cell in body[0]]
        body = body[1:]

    headers: list[str] = []
    for index, cell in enumerate(header_cells):
        name, inline_unit = _split_unit(cell)
        headers.append(name)
        # A dedicated units row wins over one parsed out of the header text: the document
        # set it out as its own row, which is a clearer statement of intent than
        # punctuation inside a label.
        if inline_unit and units[index] is None:
            units[index] = inline_unit

    # A column the document left unnamed still needs a name, because retrieval and
    # citation both address columns by name. Numbering by position is honest about
    # having nothing better, where an empty string would read as a name that is blank.
    named = tuple(header or f"Column {index + 1}" for index, header in enumerate(headers))

    return TableStructure(
        headers=named,
        units=tuple(units),
        rows=body,
        was_ragged=ragged,
        header_assumed=header_assumed,
    )
