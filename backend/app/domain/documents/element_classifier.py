"""Decide what kind of thing an element is, from how it is set and what it says.

A PDF records how text was drawn and nothing about what it means. A heading is not
marked as one; it is simply larger, or heavier, or shorter than what surrounds it. This
is where those appearances are read as structure, so that a retrieved fragment can be
shown as part of a section rather than as an orphaned paragraph, and so a table's rows
never end up flattened into the prose around them.

Every rule here is relative to the page it is on. Absolute type sizes say nothing: a
sixteen-point line is a heading on a page of ten-point body text and is ordinary prose on
a page set entirely in sixteen. Comparing against the page's own body size is what makes
the same rule work for a textbook, a slide deck and a large-print edition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.enums import ElementType
from app.domain.invariants import require_non_negative, require_positive

# "Figure 4.2", "Fig. 1", "Table 3", "Chart 2b" — a label leading the line. Captions are
# the one element type that announces itself, which is why this is checked before the
# appearance-based rules that could otherwise claim the same line.
_CAPTION_LABEL = re.compile(
    r"^\s*(?:fig(?:ure|\.)?|table|chart|diagram|exhibit|plate|scheme)\s*\.?\s*\d",
    re.IGNORECASE,
)

# Bullet characters, hoisted out of the pattern so the suppression can sit on a real
# source line: en and em dashes genuinely are used as bullets in print, so the linter's
# suggestion to replace them with hyphens would narrow what this matches.
_BULLETS = "-•*·‣▪◦–—"  # noqa: RUF001

# A bullet, or a number or letter followed by a delimiter, at the start of the line.
_LIST_MARKER = re.compile(
    rf"""^\s*(?:
          [{re.escape(_BULLETS)}]\s
        | \(?\d{{1,3}}[.)]\s
        | \(?[a-zA-Z][.)]\s
        | \(?[ivxlcdm]{{1,5}}[.)]\s
    )""",
    re.VERBOSE,
)

# Symbols that appear in mathematics and almost nowhere else. Deliberately excludes the
# arithmetic operators and brackets that ordinary prose is full of — a sentence with a
# hyphen and a bracket is not a formula, and counting those would make it one.
# Characters here are deliberately the ones a linter calls ambiguous: they look like
# Latin letters and are not, which is exactly why a formula needs recognising by them.
_MATHEMATICAL = set(
    "∑∫∂√∇±×÷≤≥≠≈≡∞∝⊂⊆⊃⊇∈∉∀∃∧∨¬→←↔⇒⇔∪∩∅ƒΣΠΔΩαβγδεθλμνξπρστφχψω"  # noqa: RUF001
)

_SENTENCE_ENDINGS = ".!?:;"


@dataclass(frozen=True, slots=True)
class ElementSignals:
    """How one element is set, and what the page around it looks like.

    Only measurements the parser can take are carried here. Everything derivable from the
    text itself is derived by the classifier, so the rules about wording live in one place
    rather than being half-computed by whoever gathered the signals.
    """

    text: str
    #: Representative type size of this element.
    font_size: float
    #: The dominant type size on the page, which is what this element is judged against.
    page_body_font_size: float
    is_bold: bool
    line_count: int

    def __post_init__(self) -> None:
        require_positive(self.font_size, "ElementSignals.font_size")
        require_positive(self.page_body_font_size, "ElementSignals.page_body_font_size")
        require_non_negative(self.line_count, "ElementSignals.line_count")

    @property
    def size_ratio(self) -> float:
        """How much larger this element is set than the body of its page."""
        return self.font_size / self.page_body_font_size


class ElementClassifier:
    """Assign an `ElementType` from element signals.

    Rules run in priority order and the first match wins. The ordering is the policy:
    the two rules that read the text — captions and list items — come before the rules
    that read the setting, because a caption is frequently bold and short and would
    otherwise be claimed as a heading, and a list item is short for the same reason.

    Table and figure regions are not decided here. They are found by looking at the page
    rather than at a run of text, so the parser types them directly.
    """

    def __init__(
        self,
        *,
        heading_size_ratio: float,
        heading_max_lines: int,
        formula_symbol_ratio: float,
    ) -> None:
        self._heading_size_ratio = heading_size_ratio
        self._heading_max_lines = heading_max_lines
        self._formula_symbol_ratio = formula_symbol_ratio

    def classify(self, signals: ElementSignals) -> ElementType:
        text = signals.text.strip()
        if not text:
            return ElementType.PARAGRAPH

        if _CAPTION_LABEL.match(text):
            return ElementType.CAPTION

        if _LIST_MARKER.match(text):
            return ElementType.LIST

        if _symbol_ratio(text) >= self._formula_symbol_ratio:
            return ElementType.FORMULA

        if self._reads_as_heading(signals, text):
            return ElementType.HEADING

        return ElementType.PARAGRAPH

    def _reads_as_heading(self, signals: ElementSignals, text: str) -> bool:
        """Whether this element is set apart from the page's body text as a title.

        A heading is short and unpunctuated, and then either larger than the body text or
        merely heavier than it. Requiring shortness of both forms is what stops an
        emphasised sentence inside a paragraph from being promoted, and judging size
        against the page rather than against a fixed number is what stops every line of a
        large-print page from being promoted at once.
        """
        if signals.line_count > self._heading_max_lines:
            return False
        if text[-1] in _SENTENCE_ENDINGS:
            return False
        return signals.size_ratio >= self._heading_size_ratio or signals.is_bold


def _symbol_ratio(text: str) -> float:
    """Share of the visible characters that are mathematical symbols."""
    visible = [character for character in text if not character.isspace()]
    if not visible:
        return 0.0
    return sum(character in _MATHEMATICAL for character in visible) / len(visible)
