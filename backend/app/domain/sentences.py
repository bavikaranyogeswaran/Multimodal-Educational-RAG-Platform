"""Where one sentence ends and the next begins.

Two places need this and they must agree. Chunking splits an oversized paragraph on
sentences; compression selects whole sentences out of a passage. If the two used different
rules, compression could cut inside something chunking had treated as indivisible, and the
disagreement would show up as a passage that reads as though a clause went missing —
without either side being wrong on its own terms.

The rule is deliberately conservative: terminal punctuation, whitespace, then a capital or
a digit. It declines to split "Fig. 4 shows" or "0.91 accuracy", and it will miss a genuine
boundary written without a following capital. That asymmetry is intended. A missed boundary
leaves two sentences joined, which is merely longer; a wrong one cuts a sentence in half,
and half a sentence misleads whoever reads it and is retrievable by nothing.
"""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def split_sentences(text: str) -> list[str]:
    """The sentences in `text`, in order, with surrounding whitespace removed.

    Text carrying no boundary comes back as a single piece rather than as nothing, so a
    caller can treat the result as "the units this passage is made of" without a special
    case for prose that happens to be one sentence long.
    """
    return [piece.strip() for piece in _SENTENCE_END.split(text) if piece.strip()]
