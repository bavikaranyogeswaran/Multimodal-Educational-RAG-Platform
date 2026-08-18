"""Count tokens the way the embedding model will count them.

Chunk sizes are specified in tokens because that is the unit the model actually works in.
Counting characters and dividing was close enough to look right and wrong in the way that
matters: English averages roughly four characters to a token, but a page of formulae,
identifiers or table cells averages far fewer, so exactly the passages most likely to be
dense are the ones the estimate most overshoots. A chunk built to a estimated 500 tokens
can arrive at the model as 800 and be silently truncated, and the part that disappears is
the end — which is where a paragraph usually says what it was getting at.

So the count comes from the model's own vocabulary. This is the tokenizer library alone,
without the weights: the same word pieces, none of the gigabytes.
"""

from __future__ import annotations

import structlog
from tokenizers import Tokenizer

_log = structlog.get_logger(__name__)


class HuggingFaceTokenCounter:
    """`TokenCounterPort` over the vocabulary of a named model.

    The vocabulary is fetched once at construction and held for the process lifetime.
    Constructing this at startup rather than on first use is deliberate: it needs the
    network the first time, and a worker that discovers that halfway through ingesting a
    textbook fails a job over something that was wrong before it began.
    """

    def __init__(self, *, model_id: str, max_input_tokens: int) -> None:
        try:
            self._tokenizer = Tokenizer.from_pretrained(model_id)
        except Exception as exc:
            raise RuntimeError(
                f"could not load the tokenizer vocabulary for {model_id!r}. "
                "Chunk sizes are specified in tokens and cannot be counted without it; "
                "refusing to fall back to an estimate, which would size chunks wrongly "
                "and silently"
            ) from exc

        self._max_input_tokens = max_input_tokens
        _log.info(
            "token_counter_ready",
            model_id=model_id,
            vocab_size=self._tokenizer.get_vocab_size(),
            max_input_tokens=max_input_tokens,
        )

    @property
    def max_input_tokens(self) -> int:
        return self._max_input_tokens

    def count(self, text: str) -> int:
        """Tokens in `text`, excluding the markers the model adds around an input.

        Special tokens are left out because this answers how large a passage is, and a
        passage does not change size by being submitted. What they cost is accounted for
        once, in the headroom the chunk ceiling leaves against the model's limit.
        """
        if not text:
            return 0
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def fits(self, text: str) -> bool:
        """Whether `text` would reach the model whole rather than truncated."""
        return self.count(text) + _SPECIAL_TOKEN_ALLOWANCE <= self._max_input_tokens


#: A leading and a trailing marker, which every input carries and no caller writes.
_SPECIAL_TOKEN_ALLOWANCE = 2
