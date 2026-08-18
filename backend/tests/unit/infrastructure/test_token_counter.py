"""Tests for HuggingFaceTokenCounter.

The counter exists because a character estimate is wrong in a direction that hides. It is
close on ordinary prose, which is what anyone spot-checks, and badly low on formulae,
identifiers and table cells — so exactly the passages most likely to be dense are the ones
sized most generously, and a chunk built to fit arrives over the model's limit with its
end quietly removed. These tests pin that divergence rather than only the arithmetic.

The vocabulary is fetched once and cached by the tokenizer library. Where it cannot be
reached at all these tests skip rather than fail, because an unreachable download says
nothing about whether the counter is correct.
"""

from __future__ import annotations

import pytest

from app.infrastructure.tokenization.token_counter import HuggingFaceTokenCounter

_MODEL_ID = "BAAI/bge-small-en-v1.5"

# The signatures below are long enough without the full class name in each one.
Counter = HuggingFaceTokenCounter


@pytest.fixture(scope="module")
def counter() -> Counter:
    try:
        return HuggingFaceTokenCounter(model_id=_MODEL_ID, max_input_tokens=512)
    except RuntimeError as exc:  # pragma: no cover - depends on the machine, not the code
        pytest.skip(f"tokenizer vocabulary unavailable: {exc}")


class TestCounting:
    def test_a_sentence_counts_more_than_its_words(self, counter: Counter) -> None:
        """Word pieces, not words: the count is the model's unit, not English's."""
        assert counter.count("Backpropagation computes the gradient") >= 4

    def test_empty_text_is_zero(self, counter: Counter) -> None:
        assert counter.count("") == 0

    def test_counting_excludes_the_markers_the_model_adds(self, counter: Counter) -> None:
        """A passage does not change size by being submitted, so the two tokens every
        input carries are accounted for in the headroom rather than in the passage."""
        assert counter.count("hello world") == 2

    def test_longer_text_counts_higher(self, counter: Counter) -> None:
        short = counter.count("The algorithm converges.")
        long = counter.count("The algorithm converges after a considerable number of steps.")
        assert long > short

    def test_counting_is_stable(self, counter: Counter) -> None:
        text = "Gradients flow backwards through the network."
        assert counter.count(text) == counter.count(text)


class TestWhereTheEstimateFails:
    """The reason this exists rather than a division by four."""

    def test_prose_is_roughly_what_the_estimate_predicted(self, counter: Counter) -> None:
        text = "Backpropagation computes the gradient of the loss function."
        estimate = len(text) // 4
        assert abs(counter.count(text) - estimate) <= estimate * 0.4

    def test_a_formula_costs_far_more_than_its_length_suggests(self, counter: Counter) -> None:
        """Symbols and identifiers fragment into many pieces each."""
        text = "x = f(theta); dL/dtheta = 0.0031"
        assert counter.count(text) > len(text) // 4

    def test_table_rows_cost_far_more_than_their_length_suggests(self, counter: Counter) -> None:
        text = "Run | Accuracy | 1 | 0.91 | 2 | 0.94"
        assert counter.count(text) > len(text) // 4

    def test_the_gap_is_large_enough_to_overrun_a_limit(self, counter: Counter) -> None:
        """Not a rounding difference. A chunk sized by the estimate can arrive at
        something close to twice its supposed length."""
        dense = "x = f(theta); dL/dtheta = 0.0031 " * 20
        assert counter.count(dense) > (len(dense) // 4) * 1.5


class TestFitting:
    def test_a_short_passage_fits(self, counter: Counter) -> None:
        assert counter.fits("A short passage.")

    def test_a_passage_beyond_the_limit_does_not(self, counter: Counter) -> None:
        assert not counter.fits("word " * 5000)

    def test_the_limit_leaves_room_for_the_markers(self) -> None:
        """A passage that exactly fills the window would overflow once the model adds
        its own two tokens, so fitting is judged with that room reserved."""
        tight = HuggingFaceTokenCounter(model_id=_MODEL_ID, max_input_tokens=4)
        assert tight.count("hello world") == 2
        assert not tight.fits("hello there world")

    def test_the_configured_limit_is_reported(self, counter: Counter) -> None:
        assert counter.max_input_tokens == 512


class TestFailingLoudly:
    def test_an_unknown_vocabulary_raises_rather_than_estimating(self) -> None:
        """There is no fallback on purpose. A counter that quietly estimated would size
        every chunk wrongly and nothing downstream would show it."""
        with pytest.raises(RuntimeError, match="could not load the tokenizer"):
            HuggingFaceTokenCounter(
                model_id="not-a-real-org/not-a-real-model", max_input_tokens=512
            )
