"""Tests for ExpansionRules.

The rules decide when a retrieved fragment is unreadable without the section around it.
They are deliberately narrow, and the tests are written around that asymmetry: a missed
expansion leaves the passage exactly as retrieval found it, which is usually fine, while a
wrong one replaces a precise passage with a section several times its size and spends the
budget doing it. So there are as many tests here for what is *not* expanded as for what is.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.documents.chunks import Chunk
from app.domain.enums import ChunkType
from app.domain.retrieval.expansion import ExpansionReason, ExpansionRules
from app.domain.values import UntrustedText

_NOW = datetime(2025, 6, 1, tzinfo=UTC)


def _chunk(
    text: str,
    *,
    chunk_type: ChunkType = ChunkType.TEXT,
    has_parent: bool = True,
) -> Chunk:
    return Chunk(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        parent_chunk_id=uuid.uuid4() if has_parent else None,
        chunk_type=chunk_type,
        text=UntrustedText(text),
        token_count=max(1, len(text.split())),
        ordinal=0,
        page_start=1,
        page_end=1,
        index_version=1,
        created_at=_NOW,
    )


def _reason(text: str, **kwargs: object) -> ExpansionReason | None:
    return ExpansionRules().reason_to_expand(_chunk(text, **kwargs))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Fragments that begin somewhere else
# ---------------------------------------------------------------------------


class TestIncompleteOpenings:
    def test_a_passage_starting_mid_sentence_needs_its_section(self) -> None:
        """Boundaries never land inside a sentence by design, so a lowercase opening
        means the sentence began in the previous chunk."""
        assert _reason("and therefore the loss stops falling entirely.") is (
            ExpansionReason.OPENS_MID_EXPLANATION
        )

    @pytest.mark.parametrize(
        "opener", ["However", "Therefore", "Thus", "Consequently", "Instead", "Moreover"]
    )
    def test_a_continuation_word_needs_its_section(self, opener: str) -> None:
        assert _reason(f"{opener}, the gradient vanishes before it reaches the input.") is (
            ExpansionReason.OPENS_MID_EXPLANATION
        )

    @pytest.mark.parametrize("opener", ["This", "These", "It", "They", "Such", "Their"])
    def test_an_opening_reference_needs_its_section(self, opener: str) -> None:
        """The thing being pointed at is in a different chunk."""
        assert _reason(f"{opener} means the gradient vanishes on the way back.") is (
            ExpansionReason.OPENS_WITH_A_REFERENCE
        )

    def test_a_quoted_opening_is_seen_past(self) -> None:
        assert _reason('"This means the gradient vanishes on the way back."') is (
            ExpansionReason.OPENS_WITH_A_REFERENCE
        )

    def test_a_self_contained_paragraph_is_left_alone(self) -> None:
        assert _reason("Backpropagation computes the gradient of the loss.") is None

    def test_a_pronoun_later_in_the_passage_is_not_enough(self) -> None:
        """It refers to a subject the passage has already introduced. Only the ones at
        the very front reach backwards out of the chunk."""
        assert _reason("Backpropagation is efficient. It reuses partial results.") is None

    def test_a_heading_style_opening_is_left_alone(self) -> None:
        assert _reason("Gradient Descent\n\nThe method proceeds in steps.") is None


# ---------------------------------------------------------------------------
# Kinds of content whose meaning sits beside them
# ---------------------------------------------------------------------------


class TestIncompleteKinds:
    def test_a_table_without_a_caption_needs_its_section(self) -> None:
        """Otherwise it is a grid of numbers with column headings and no subject."""
        rows = "Run | Accuracy\n1 | 0.91\n2 | 0.94"
        assert _reason(rows, chunk_type=ChunkType.TABLE) is (
            ExpansionReason.TABLE_WITHOUT_ITS_CAPTION
        )

    def test_a_table_carrying_its_caption_is_left_alone(self) -> None:
        rows = "Table 3: accuracy by run\nRun | Accuracy\n1 | 0.91"
        assert _reason(rows, chunk_type=ChunkType.TABLE) is None

    def test_a_formula_without_its_definitions_needs_its_section(self) -> None:
        assert _reason("y = f(Wx + b)", chunk_type=ChunkType.FORMULA) is (
            ExpansionReason.FORMULA_WITHOUT_ITS_DEFINITION
        )

    def test_a_formula_defining_its_own_symbols_is_left_alone(self) -> None:
        assert _reason(
            "y = f(Wx + b), where W denotes the weight matrix and b the bias.",
            chunk_type=ChunkType.FORMULA,
        ) is None

    @pytest.mark.parametrize(
        "chunk_type", [ChunkType.FIGURE, ChunkType.CHART, ChunkType.DIAGRAM]
    )
    def test_a_visual_needs_the_prose_beside_it(self, chunk_type: ChunkType) -> None:
        """A caption says what the picture is of, not what it shows."""
        assert _reason("Figure 4: the training curve", chunk_type=chunk_type) is (
            ExpansionReason.VISUAL_WITHOUT_ITS_EXPLANATION
        )


# ---------------------------------------------------------------------------
# When there is nothing to expand into
# ---------------------------------------------------------------------------


class TestNothingToExpandInto:
    def test_a_chunk_with_no_parent_is_never_expanded(self) -> None:
        """Saying otherwise sends the caller looking for a row that does not exist."""
        assert _reason("This means the gradient vanishes.", has_parent=False) is None

    def test_a_parentless_table_is_not_expanded_either(self) -> None:
        assert _reason(
            "Run | Accuracy\n1 | 0.91", chunk_type=ChunkType.TABLE, has_parent=False
        ) is None
