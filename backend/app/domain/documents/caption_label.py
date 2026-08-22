"""Reading the label a document puts at the front of a caption.

A textbook names its objects — "Table 4.2", "Fig. 3", "Chart 2b" — and students refer to
them that way. Keeping the number as data rather than leaving it inside a sentence is
what lets "what does table 4.2 show" resolve to a particular table, and what lets a
claim citing a table number be checked against the tables that were actually supplied.

Two things were already matching these labels for their own purposes: the element
classifier, deciding that a line is a caption, and table extraction, deciding that a
caption belongs to a table rather than a figure beside it. Both now ask this module, so
there is one statement of what a label looks like instead of three that drift apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.enums import ElementType

# What the label calls the thing, mapped to what this system calls it. Plate and exhibit
# are older names for a figure and scheme for a diagram; they are read as such because a
# reader means the same thing by them, and refusing to recognise them would leave those
# objects unnumbered rather than correctly named.
_KINDS: dict[str, ElementType] = {
    "fig": ElementType.FIGURE,
    "figure": ElementType.FIGURE,
    "plate": ElementType.FIGURE,
    "exhibit": ElementType.FIGURE,
    "table": ElementType.TABLE,
    "tbl": ElementType.TABLE,
    "chart": ElementType.CHART,
    "diagram": ElementType.DIAGRAM,
    "scheme": ElementType.DIAGRAM,
}

# A label leading the line: the word, an optional abbreviating full stop, then the
# number. The number may be sectioned ("4.2", "12.3.1"), hyphenated ("4-2"), lettered
# for an appendix ("A.1"), or suffixed for a sibling ("2b"). It must contain a digit —
# without one, "Table of contents" and "Figure it out" would both read as labels.
_LABEL = re.compile(
    r"""^\s*
    (?P<kind>fig(?:ure)?|table|tbl|chart|diagram|exhibit|plate|scheme)
    \s*\.?\s*
    (?P<number>[A-Z]?\.?\d+(?:[.\-]\d+)*[a-z]?)
    (?!\w)
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class CaptionLabel:
    """What a caption calls its object, and which number it gave it."""

    kind: ElementType
    number: str

    def __str__(self) -> str:
        return f"{self.kind.value.title()} {self.number}"


def parse_caption_label(text: str) -> CaptionLabel | None:
    """The label leading a caption, or None where the line does not carry one.

    The number is kept as the document wrote it rather than parsed into parts. "4.2" and
    "4-2" are different strings because they are different on the page, and a student who
    types what they see should match what was printed.
    """
    match = _LABEL.match(text)
    if match is None:
        return None

    kind = _KINDS.get(match.group("kind").lower())
    if kind is None:  # pragma: no cover - every alternation branch is in the mapping
        return None

    # A stray full stop can be picked up by the appendix-letter branch when there is no
    # letter, as in "Table .5". Trimming it keeps the stored number to what was meant.
    return CaptionLabel(kind=kind, number=match.group("number").strip(". "))


def has_caption_label(text: str) -> bool:
    """Whether a line announces itself as a caption."""
    return _LABEL.match(text) is not None


def contains_caption_label(text: str, kind: ElementType) -> bool:
    """Whether a label for one kind of object appears at the start of any line.

    Asks a different question from the others: not "is this line a caption" but "does
    this passage still carry the caption that says what it is about". A table separated
    from its caption is a grid of numbers with column headings and no subject, and
    knowing that is what decides whether the passage around it has to be fetched.
    """
    return any(labels_kind(line, kind) for line in text.splitlines())


def labels_kind(text: str, kind: ElementType) -> bool:
    """Whether a line is a caption for one particular kind of object.

    Used where a caption sits between two objects and only one of them can claim it —
    attaching a figure's caption to a table would describe the wrong thing entirely.
    """
    label = parse_caption_label(text)
    return label is not None and label.kind is kind
