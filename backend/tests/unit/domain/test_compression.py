"""Tests for EvidenceCompressor.

Compression is the one stage that can make an answer wrong while making everything look
better. A shortened passage still reads fluently, still carries a citation, and still comes
from the document — and if the sentence that went was the one saying the method does not
converge, the answer is now confidently the opposite of the source, with a reference
attached to prove it.

So the tests here are mostly about what cannot be removed. The last class is the property
test the plan asks for: over generated passages, no number, unit or negation present in the
original is ever absent from the result.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import pytest

from app.domain.documents.chunks import Chunk
from app.domain.enums import ChunkType, RetrieverKind
from app.domain.errors import InvariantViolationError
from app.domain.retrieval.compression import EvidenceCompressor
from app.domain.retrieval.entities import Evidence, EvidenceLabel
from app.domain.values import UntrustedText

_NOW = datetime(2025, 6, 1, tzinfo=UTC)
_QUERY = "how does backpropagation compute gradients"


def _count_words(text: str) -> int:
    return len(text.split())


def _compressor(*, budget: int = 40) -> EvidenceCompressor:
    return EvidenceCompressor(_count_words, token_budget=budget)


def _evidence(text: str, *, chunk_type: ChunkType = ChunkType.TEXT, rank: int = 0) -> Evidence:
    return Evidence(
        label=EvidenceLabel(rank + 1),
        chunk=Chunk(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            knowledge_base_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            chunk_type=chunk_type,
            text=UntrustedText(text),
            token_count=max(1, len(text.split())),
            ordinal=rank,
            page_start=1,
            page_end=1,
            index_version=1,
            created_at=_NOW,
        ),
        retrievers=frozenset({RetrieverKind.DENSE}),
        rank=rank,
    )


_FILLER = " ".join(
    [
        "Backpropagation computes the gradient of the loss with respect to each weight.",
        "The chain rule is applied backwards through the layers of the network.",
        "Partial results are reused so the cost stays linear in the number of layers.",
        "The method was popularised in the nineteen eighties by several authors at once.",
        "Implementations differ in how they store the intermediate activations.",
        "Some frameworks recompute them instead to save memory during training.",
    ]
)


def _text_of(result: list[Evidence]) -> str:
    return result[0].chunk.text.value


# ---------------------------------------------------------------------------
# What is never removed
# ---------------------------------------------------------------------------


class TestLoadBearingSentences:
    def test_a_negation_survives_compression(self) -> None:
        """Drop it and the passage reads as an unqualified endorsement, fluently and with
        a citation attached."""
        text = f"{_FILLER} The method does not converge for non-convex losses."
        result = _compressor(budget=20).compress([_evidence(text)], query=_QUERY)
        assert "does not converge" in _text_of(result)

    def test_a_contracted_negation_survives(self) -> None:
        text = f"{_FILLER} It doesn't converge for non-convex losses."
        result = _compressor(budget=20).compress([_evidence(text)], query=_QUERY)
        assert "converge" in _text_of(result)

    def test_a_number_and_its_unit_survive(self) -> None:
        """Units need no rule of their own: they sit in the sentence with their number."""
        text = f"{_FILLER} Training took 4.5 hours on a single GPU."
        result = _compressor(budget=20).compress([_evidence(text)], query=_QUERY)
        kept = _text_of(result)
        assert "4.5" in kept
        assert "hours" in kept

    def test_a_condition_survives(self) -> None:
        text = f"{_FILLER} This holds only if the learning rate is small enough."
        result = _compressor(budget=20).compress([_evidence(text)], query=_QUERY)
        assert "only if" in _text_of(result)

    def test_ordinary_prose_is_what_gets_dropped(self) -> None:
        text = f"{_FILLER} The method does not converge for non-convex losses."
        result = _compressor(budget=20).compress([_evidence(text)], query=_QUERY)
        assert len(_text_of(result)) < len(text)

    def test_required_sentences_are_kept_even_past_the_budget(self) -> None:
        """A passage that fits and misleads is worse than one longer than planned."""
        text = " ".join(f"Step {i} must not be skipped under any circumstances." for i in range(6))
        result = _compressor(budget=5).compress([_evidence(text)], query=_QUERY)
        assert _text_of(result) == text


# ---------------------------------------------------------------------------
# What is not cut by sentence at all
# ---------------------------------------------------------------------------


class TestStructuredContent:
    def test_a_table_keeps_its_title_and_headers(self) -> None:
        """Without them the rows are numbers in unnamed columns, which is confidently
        wrong rather than merely long."""
        rows = "\n".join(f"run{i} | 0.9{i} | seconds" for i in range(12))
        text = f"Table 3: accuracy by run\nRun | Accuracy | Unit\n{rows}"
        # The query matches neither the title nor the headings, and the budget leaves
        # room for only two lines, so both survive because they are kept unconditionally
        # rather than because they scored or happened to come first.
        result = _compressor(budget=10).compress(
            [_evidence(text, chunk_type=ChunkType.TABLE)], query="run7"
        )
        kept = _text_of(result)
        assert "Table 3: accuracy by run" in kept
        assert "Run | Accuracy | Unit" in kept

    def test_a_table_keeps_the_rows_that_were_asked_about(self) -> None:
        rows = "\n".join(f"run{i} | 0.9{i} | seconds" for i in range(12))
        text = f"Table 3: accuracy by run\nRun | Accuracy | Unit\n{rows}"
        result = _compressor(budget=20).compress(
            [_evidence(text, chunk_type=ChunkType.TABLE)], query="run7"
        )
        assert "run7" in _text_of(result)

    @pytest.mark.parametrize(
        "chunk_type", [ChunkType.FORMULA, ChunkType.FIGURE, ChunkType.CHART, ChunkType.DIAGRAM]
    )
    def test_indivisible_content_is_sent_whole(self, chunk_type: ChunkType) -> None:
        """Written with real sentence boundaries, so that cutting it by sentence would
        visibly shorten it — the point being that nothing here does."""
        text = (
            "Figure 4 shows the training curve for the reference model. "
            "The curve falls steeply and then flattens out. "
            "Readers often misjudge how long the tail continues."
        )
        result = _compressor(budget=5).compress(
            [_evidence(text, chunk_type=chunk_type)], query=_QUERY
        )
        assert _text_of(result) == text
        assert result[0].compressed is False


# ---------------------------------------------------------------------------
# When compression happens at all
# ---------------------------------------------------------------------------


class TestWhenItRuns:
    def test_a_passage_that_already_fits_is_untouched(self) -> None:
        """Shortening it could only lose something and would save nothing."""
        text = "Backpropagation computes the gradient. The chain rule is applied backwards."
        result = _compressor(budget=1000).compress([_evidence(text)], query=_QUERY)
        assert _text_of(result) == text
        assert result[0].compressed is False

    def test_a_passage_that_fits_keeps_its_own_formatting(self) -> None:
        """Not merely the same words: the same text. Rebuilding a passage that needed
        nothing doing to it would flatten its paragraph breaks and mark it compressed,
        so a reader comparing it against the document would find it subtly altered."""
        text = "Backpropagation computes the gradient.\n\nThe chain rule runs backwards."
        result = _compressor(budget=1000).compress([_evidence(text)], query=_QUERY)
        assert _text_of(result) == text
        assert result[0].compressed is False

    def test_a_compressed_passage_is_marked_as_such(self) -> None:
        result = _compressor(budget=15).compress([_evidence(_FILLER)], query=_QUERY)
        assert result[0].compressed is True

    def test_the_kept_text_is_word_for_word_from_the_source(self) -> None:
        """The only kind of shortening a citation can survive."""
        result = _compressor(budget=15).compress([_evidence(_FILLER)], query=_QUERY)
        for sentence in _text_of(result).split(". "):
            assert sentence.strip(". ") in _FILLER

    def test_sentences_stay_in_the_order_the_passage_said_them(self) -> None:
        result = _compressor(budget=25).compress([_evidence(_FILLER)], query=_QUERY)
        kept = _text_of(result)
        positions = [_FILLER.index(s) for s in kept.split(". ") if s.strip(". ") in _FILLER]
        assert positions == sorted(positions)

    def test_a_single_sentence_passage_is_left_alone(self) -> None:
        text = " ".join(f"word{i}" for i in range(50))
        result = _compressor(budget=5).compress([_evidence(text)], query=_QUERY)
        assert _text_of(result) == text

    def test_an_early_passage_leaves_room_for_a_later_one(self) -> None:
        """Each passage is offered an equal share of what the ones before it left, so a
        short passage hands its unused room on."""
        short = _evidence("Backpropagation computes gradients.", rank=0)
        long = _evidence(_FILLER, rank=1)
        result = _compressor(budget=60).compress([short, long], query=_QUERY)
        assert result[0].chunk.text.value == "Backpropagation computes gradients."
        assert len(result) == 2

    def test_no_evidence_compresses_to_nothing(self) -> None:
        assert _compressor().compress([], query=_QUERY) == []


# ---------------------------------------------------------------------------
# Generative compression
# ---------------------------------------------------------------------------


class TestGenerativeCompression:
    def test_enabling_it_is_refused(self) -> None:
        """The flag records a decision rather than offering a choice: a summarised
        passage is no longer the text the citation points at."""
        with pytest.raises(InvariantViolationError, match="generative"):
            EvidenceCompressor(_count_words, token_budget=100, generative_enabled=True)


# ---------------------------------------------------------------------------
# The property the plan asks for
# ---------------------------------------------------------------------------


_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_NEGATION_WORDS = ("not", "never", "cannot", "without", "no")

_CLAIMS = [
    "The error rate fell to 3.2 percent after 40 epochs of training.",
    "The model does not generalise to unseen distributions.",
    "Convergence requires at least 128 samples per batch.",
    "It never exceeds 12 milliseconds on the reference hardware.",
    "Accuracy reaches 0.91 without any additional regularisation.",
    "The bound holds only if the step size stays below 0.05.",
]


class TestCompressionNeverLosesTheLoadBearingParts:
    @pytest.mark.parametrize("claim", _CLAIMS)
    @pytest.mark.parametrize("budget", [5, 10, 20, 40])
    def test_no_number_or_negation_is_ever_dropped(self, claim: str, budget: int) -> None:
        """Generated across budgets tight enough to force real cutting. Whatever else
        goes, every number and every negation in the source is still there."""
        text = f"{_FILLER} {claim}"
        result = _compressor(budget=budget).compress([_evidence(text)], query=_QUERY)
        kept = _text_of(result)

        for number in _NUMBER.findall(claim):
            assert number in kept, f"lost {number!r} at budget {budget}"
        for word in _NEGATION_WORDS:
            if re.search(rf"\b{word}\b", claim):
                assert re.search(rf"\b{word}\b", kept), f"lost {word!r} at budget {budget}"

    @pytest.mark.parametrize("budget", [5, 10, 20, 40])
    def test_several_claims_at_once_all_survive(self, budget: int) -> None:
        text = f"{_FILLER} " + " ".join(_CLAIMS)
        kept = _text_of(_compressor(budget=budget).compress([_evidence(text)], query=_QUERY))
        for claim in _CLAIMS:
            for number in _NUMBER.findall(claim):
                assert number in kept, f"lost {number!r} at budget {budget}"
