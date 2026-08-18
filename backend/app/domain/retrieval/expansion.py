"""Decide which retrieved fragments cannot be understood without the section around them.

Chunks were cut small so that a search matches a passage rather than a chapter. That is the
right size to match and sometimes the wrong size to read: a paragraph beginning "This means
the gradient vanishes" is precisely on topic and says nothing on its own, because what
"this" refers to was two paragraphs earlier and is now in a different chunk.

The obvious remedy — send the parent every time — is worse than the problem. Parents are
several times the size, so replacing every child spends the whole token budget on four
passages instead of eight, and buries the sentence that actually matched inside a section
of mostly irrelevant prose. The model then has more to read and less reason to trust any
particular line of it.

So expansion is the exception, and this module is the list of cases where the exception
applies. Each one is a way a fragment can be incomplete *in itself*, visible from the text
without knowing what the question was: it opens in the middle of an explanation, it opens
by pointing at something it does not contain, or it is a kind of content — a table, a
formula, a figure — whose meaning conventionally lives in the prose beside it rather than
inside it.

The rules are deliberately narrow, and the asymmetry is the reason. A missed expansion
leaves a passage exactly as retrieval found it, which is the status quo and is often fine.
A wrong expansion replaces a precise passage with a diffuse one and costs several times its
size in budget. Where a rule would have to guess, it declines.
"""

from __future__ import annotations

import re
from enum import StrEnum

from app.domain.documents.chunks import Chunk
from app.domain.enums import ChunkType


class ExpansionReason(StrEnum):
    """Why a fragment was judged incomplete, recorded so the decision can be reviewed."""

    OPENS_MID_EXPLANATION = "OPENS_MID_EXPLANATION"
    OPENS_WITH_A_REFERENCE = "OPENS_WITH_A_REFERENCE"
    TABLE_WITHOUT_ITS_CAPTION = "TABLE_WITHOUT_ITS_CAPTION"
    FORMULA_WITHOUT_ITS_DEFINITION = "FORMULA_WITHOUT_ITS_DEFINITION"
    VISUAL_WITHOUT_ITS_EXPLANATION = "VISUAL_WITHOUT_ITS_EXPLANATION"


#: Words that only make sense as a continuation. A passage opening with one of these is
#: resuming an argument made somewhere the reader cannot see.
_CONTINUATIONS = frozenset(
    {
        "however",
        "therefore",
        "thus",
        "hence",
        "consequently",
        "moreover",
        "furthermore",
        "instead",
        "conversely",
        "similarly",
        "nevertheless",
        "nonetheless",
        "meanwhile",
        "otherwise",
        "accordingly",
        "besides",
    }
)

#: Words that point at something rather than name it. Restricted to the opening, because a
#: pronoun later in a passage usually refers to a subject the passage has already
#: introduced — the ones that reach backwards out of the chunk are the ones at the front.
_REFERENCES = frozenset(
    {
        "this",
        "these",
        "that",
        "those",
        "it",
        "its",
        "they",
        "them",
        "their",
        "such",
        "he",
        "she",
        "his",
        "her",
    }
)

#: A table caption, which names what the rows are of. Without it a table is a grid of
#: numbers with column headings and no subject.
_TABLE_CAPTION = re.compile(r"^\s*(table|tbl\.?)\s*\d", re.IGNORECASE | re.MULTILINE)

#: Language that introduces what a symbol means. A formula carrying its own definitions
#: does not need the prose around it.
_DEFINING = re.compile(
    r"\b(where|let|denotes?|defined as|refers? to|is the|are the)\b", re.IGNORECASE
)

#: Whitespace, quotes and brackets that can sit in front of the first real word,
#: including the curly quotes a typesetter leaves behind. Written as escapes so the
#: characters themselves cannot be confused with the plain ones when read.
_OPENING_MARKS = " \t\r\n\f\v\"'([\u2018\u201c\u00ab"


#: Content that is not prose, and so cannot be read for the signs that prose gives.
_STRUCTURED = frozenset(
    {
        ChunkType.TABLE,
        ChunkType.FORMULA,
        ChunkType.FIGURE,
        ChunkType.CHART,
        ChunkType.DIAGRAM,
    }
)


class ExpansionRules:
    """Whether a fragment has to be read with its parent to mean anything."""

    def reason_to_expand(self, chunk: Chunk) -> ExpansionReason | None:
        """Why this fragment is incomplete on its own, or `None` if it is not.

        A chunk with no parent recorded is never expanded — there is nothing to expand
        into, and saying otherwise would send whoever acts on this looking for a row that
        does not exist.
        """
        if chunk.parent_chunk_id is None:
            return None
        if chunk.chunk_type in _STRUCTURED:
            # Judged by what they are, never by how they open. Notation and tabular
            # text are not sentences: a formula routinely begins with a lowercase
            # symbol and a row with a bare number, and neither says anything about
            # whether the passage began somewhere else.
            return _incomplete_kind(chunk)
        return _incomplete_opening(chunk.text.value)


def _incomplete_kind(chunk: Chunk) -> ExpansionReason | None:
    """Kinds of content whose meaning conventionally sits beside them, not inside them."""
    text = chunk.text.value
    if chunk.chunk_type is ChunkType.TABLE and not _TABLE_CAPTION.search(text):
        return ExpansionReason.TABLE_WITHOUT_ITS_CAPTION
    if chunk.chunk_type is ChunkType.FORMULA and not _DEFINING.search(text):
        return ExpansionReason.FORMULA_WITHOUT_ITS_DEFINITION
    if chunk.carries_a_visual:
        return ExpansionReason.VISUAL_WITHOUT_ITS_EXPLANATION
    return None


def _incomplete_opening(text: str) -> ExpansionReason | None:
    """Ways a passage can announce, in its first word, that it began earlier."""
    opening = _first_word(text)
    if opening is None:
        return None
    if _starts_lowercase(text) or opening in _CONTINUATIONS:
        return ExpansionReason.OPENS_MID_EXPLANATION
    if opening in _REFERENCES:
        return ExpansionReason.OPENS_WITH_A_REFERENCE
    return None


def _first_word(text: str) -> str | None:
    """The first word, stripped of the quotes and brackets that can precede it."""
    stripped = text.strip(_OPENING_MARKS).strip()
    if not stripped:
        return None
    word = stripped.split(maxsplit=1)[0]
    return word.strip(".,;:!?").lower() or None


def _starts_lowercase(text: str) -> bool:
    """Whether the passage begins mid-sentence.

    A chunk boundary never lands inside a sentence by design, so a lowercase opening
    means the sentence began in the previous chunk — the clearest evidence of an
    incomplete fragment there is, and the only rule here that needs no vocabulary.
    """
    stripped = text.lstrip(_OPENING_MARKS)
    return bool(stripped) and stripped[0].isalpha() and stripped[0].islower()
