"""Tests for Chunker.

Chunking decides what a search can return, and it does so before any search exists. A
boundary in the wrong place removes an answer from the index permanently — the sentence
that resolves a question sits half in one chunk and half in the next, and neither half
says enough to be retrieved. Nothing downstream reports that; the answer is simply never
found. So the properties here are about where boundaries land, not about sizes.

Token counting is a word count, not the real vocabulary. What is under test is where the
splits go, and a fake counter keeps these tests independent of a downloaded vocabulary
while making the arithmetic legible: a target of ten tokens means ten words.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.documents.chunker import ChunkDraft, Chunker
from app.domain.documents.entities import DocumentElement
from app.domain.enums import ChunkType, ElementType, ProcessingMethod
from app.domain.values import BoundingBox, HeadingPath, UntrustedText

_NOW = datetime(2025, 6, 1, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_DOC_ID = uuid.uuid4()


def _count_words(text: str) -> int:
    return len(text.split())


def _chunker(*, target: int = 20, maximum: int = 40, overlap: int = 5) -> Chunker:
    return Chunker(
        _count_words, target_tokens=target, max_tokens=maximum, overlap_tokens=overlap
    )


def _element(
    text: str,
    *,
    element_type: ElementType = ElementType.PARAGRAPH,
    heading: tuple[str, ...] = ("Chapter One",),
    page: int = 1,
    order: int = 0,
    box: BoundingBox | None = None,
) -> DocumentElement:
    return DocumentElement(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=_DOC_ID,
        page_number=page,
        element_type=element_type,
        text=UntrustedText(text),
        reading_order=order,
        processing_method=ProcessingMethod.NATIVE_TEXT,
        created_at=_NOW,
        heading_path=HeadingPath(heading),
        bounding_box=box,
    )


def _words(n: int, *, prefix: str = "word") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def _chunk(elements: list[DocumentElement], **kwargs: int) -> list[ChunkDraft]:
    return _chunker(**kwargs).chunk(elements)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Section boundaries
# ---------------------------------------------------------------------------


class TestSectionBoundaries:
    def test_a_chunk_never_spans_two_sections(self) -> None:
        """Retrieval shows a fragment with the section it came from. A chunk straddling
        a boundary belongs to two and can be honestly labelled with neither."""
        drafts = _chunk(
            [
                _element("alpha beta", heading=("One",)),
                _element("gamma delta", heading=("Two",)),
            ]
        )
        for draft in drafts:
            assert "alpha" not in draft.text or "gamma" not in draft.text

    def test_each_section_yields_its_own_chunks(self) -> None:
        drafts = _chunk(
            [
                _element("alpha beta", heading=("One",)),
                _element("gamma delta", heading=("Two",)),
            ]
        )
        assert len(drafts) == 2

    def test_a_chunk_carries_the_heading_path_of_its_section(self) -> None:
        drafts = _chunk([_element("alpha beta", heading=("Chapter", "Section"))])
        assert drafts[0].heading_path.segments == ("Chapter", "Section")

    def test_chapter_and_section_come_from_the_path(self) -> None:
        drafts = _chunk([_element("alpha", heading=("Chapter Three", "Gradients"))])
        assert drafts[0].chapter == "Chapter Three"
        assert drafts[0].section == "Gradients"

    def test_a_section_returned_to_later_is_not_merged_with_its_earlier_run(self) -> None:
        """An appendix repeating a title is a different run of pages, and joining them
        would build a chunk out of content that never sat together."""
        drafts = _chunk(
            [
                _element("first run", heading=("Same",)),
                _element("interruption", heading=("Other",)),
                _element("second run", heading=("Same",)),
            ]
        )
        assert len(drafts) == 3


# ---------------------------------------------------------------------------
# Where the splits land
# ---------------------------------------------------------------------------


class TestSplitting:
    def test_short_content_stays_in_one_chunk(self) -> None:
        drafts = _chunk([_element("alpha beta gamma")])
        assert len(drafts) == 1
        assert drafts[0].text == "alpha beta gamma"

    def test_paragraphs_accumulate_until_the_target(self) -> None:
        drafts = _chunk(
            [_element(_words(6), order=i) for i in range(3)], target=20, maximum=40
        )
        assert len(drafts) == 1

    def test_a_new_chunk_starts_once_the_target_is_reached(self) -> None:
        drafts = _chunk(
            [_element(_words(8), order=i) for i in range(6)], target=20, maximum=40
        )
        assert len(drafts) > 1

    def test_no_chunk_splits_a_word(self) -> None:
        drafts = _chunk([_element(_words(200))], target=20, maximum=40)
        for draft in drafts:
            for word in draft.text.split():
                assert word.startswith("word")
                assert word[4:].isdigit()

    def test_an_oversized_paragraph_splits_on_sentences(self) -> None:
        """The paragraph level has failed, so sentences are the next boundary down —
        not a character count arriving mid-clause."""
        sentences = " ".join(f"Sentence number {i} says something." for i in range(20))
        drafts = _chunk([_element(sentences)], target=20, maximum=30)

        assert len(drafts) > 1
        for draft in drafts:
            assert draft.text.endswith(".")

    def test_a_sentence_is_never_cut_in_half(self) -> None:
        sentences = " ".join(f"Sentence number {i} says something." for i in range(20))
        drafts = _chunk([_element(sentences)], target=20, maximum=30)

        rejoined = " ".join(draft.text for draft in drafts)
        for i in range(20):
            assert f"Sentence number {i} says something." in rejoined


# ---------------------------------------------------------------------------
# Overlap
# ---------------------------------------------------------------------------


class TestOverlap:
    def test_consecutive_chunks_share_content(self) -> None:
        """A sentence at a boundary would otherwise be reachable from neither side."""
        drafts = _chunk(
            [_element(f"paragraph{i} " + _words(8), order=i) for i in range(6)],
            target=20,
            maximum=60,
            overlap=10,
        )
        assert len(drafts) > 1
        first_words = set(drafts[0].text.split())
        second_words = set(drafts[1].text.split())
        assert first_words & second_words

    def test_the_overlap_is_real_text_from_the_previous_chunk(self) -> None:
        """Not a restatement: a match on it points somewhere the passage exists."""
        drafts = _chunk(
            [_element(f"paragraph{i} " + _words(8), order=i) for i in range(6)],
            target=20,
            maximum=60,
            overlap=10,
        )
        shared = set(drafts[0].text.split()) & set(drafts[1].text.split())
        for word in shared:
            assert word in drafts[0].text

    def test_no_overlap_when_it_is_switched_off(self) -> None:
        drafts = _chunk(
            [_element(f"unique{i} " + _words(8), order=i) for i in range(6)],
            target=20,
            maximum=60,
            overlap=0,
        )
        markers = [
            [w for w in draft.text.split() if w.startswith("unique")] for draft in drafts
        ]
        flattened = [m for group in markers for m in group]
        assert len(flattened) == len(set(flattened))

    def test_overlap_does_not_prevent_progress(self) -> None:
        """Carrying everything forward would loop for ever without emitting anything."""
        drafts = _chunk(
            [_element(_words(10), order=i) for i in range(10)],
            target=15,
            maximum=40,
            overlap=1000,
        )
        assert len(drafts) > 1


# ---------------------------------------------------------------------------
# Tables, figures and formulas
# ---------------------------------------------------------------------------


class TestStandaloneContent:
    def test_a_table_becomes_its_own_chunk(self) -> None:
        drafts = _chunk(
            [
                _element("some prose here", order=0),
                _element("Run | Accuracy\n1 | 0.91", element_type=ElementType.TABLE, order=1),
            ]
        )
        tables = [d for d in drafts if d.chunk_type is ChunkType.TABLE]
        assert len(tables) == 1

    def test_a_table_is_never_merged_into_prose(self) -> None:
        """Rows scattered through sentences lose which column a number came from, which
        is exactly what a student asks a table about."""
        drafts = _chunk(
            [
                _element("some prose here", order=0),
                _element("Run | Accuracy\n1 | 0.91", element_type=ElementType.TABLE, order=1),
                _element("more prose after", order=2),
            ]
        )
        for draft in drafts:
            if draft.chunk_type is ChunkType.TABLE:
                assert "prose" not in draft.text
            else:
                assert "0.91" not in draft.text

    def test_a_tables_rows_stay_together(self) -> None:
        rows = "\n".join(f"row{i} | value{i}" for i in range(5))
        drafts = _chunk([_element(rows, element_type=ElementType.TABLE)])
        assert len(drafts) == 1
        assert drafts[0].text == rows

    def test_an_oversized_table_splits_on_rows_not_mid_row(self) -> None:
        rows = "\n".join(f"row{i} | value{i} | extra{i}" for i in range(30))
        drafts = _chunk([_element(rows, element_type=ElementType.TABLE)], maximum=20)

        assert len(drafts) > 1
        for draft in drafts:
            for line in draft.text.splitlines():
                assert line.count("|") == 2

    def test_prose_before_a_table_is_not_carried_past_it(self) -> None:
        drafts = _chunk(
            [
                _element("before the table", order=0),
                _element("Run | Accuracy", element_type=ElementType.TABLE, order=1),
                _element("after the table", order=2),
            ]
        )
        texts = [d.text for d in drafts]
        assert texts[0] == "before the table"
        assert "after" in texts[-1]

    @pytest.mark.parametrize(
        ("element_type", "chunk_type"),
        [
            (ElementType.TABLE, ChunkType.TABLE),
            (ElementType.FIGURE, ChunkType.FIGURE),
            (ElementType.CHART, ChunkType.CHART),
            (ElementType.DIAGRAM, ChunkType.DIAGRAM),
            (ElementType.FORMULA, ChunkType.FORMULA),
        ],
    )
    def test_element_types_map_to_chunk_types(
        self, element_type: ElementType, chunk_type: ChunkType
    ) -> None:
        drafts = _chunk([_element("content here", element_type=element_type)])
        assert drafts[0].chunk_type is chunk_type

    def test_a_figure_with_no_text_yields_no_chunk(self) -> None:
        """A chunk of nothing is not retrievable. That the figure exists is recorded on
        the element; describing it is a later stage's work."""
        drafts = _chunk([_element("", element_type=ElementType.FIGURE)])
        assert drafts == []

    def test_prose_becomes_a_text_chunk(self) -> None:
        drafts = _chunk([_element("ordinary prose here")])
        assert drafts[0].chunk_type is ChunkType.TEXT


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_pages_span_the_elements_the_chunk_came_from(self) -> None:
        drafts = _chunk(
            [_element("alpha", page=3, order=0), _element("beta", page=4, order=1)]
        )
        assert (drafts[0].page_start, drafts[0].page_end) == (3, 4)

    def test_a_uniform_chunk_reports_its_element_type(self) -> None:
        drafts = _chunk([_element("a list item", element_type=ElementType.LIST)])
        assert drafts[0].element_type is ElementType.LIST

    def test_a_mixed_chunk_reports_no_element_type(self) -> None:
        drafts = _chunk(
            [
                _element("a heading", element_type=ElementType.HEADING, order=0),
                _element("some prose", element_type=ElementType.PARAGRAPH, order=1),
            ]
        )
        assert drafts[0].element_type is None

    def test_a_box_is_merged_across_elements_on_one_page(self) -> None:
        drafts = _chunk(
            [
                _element("alpha", page=1, order=0, box=BoundingBox(10, 700, 100, 720)),
                _element("beta", page=1, order=1, box=BoundingBox(10, 650, 120, 690)),
            ]
        )
        box = drafts[0].bounding_box
        assert box is not None
        assert (box.x0, box.y0, box.x1, box.y1) == (10, 650, 120, 720)

    def test_no_box_is_reported_across_two_pages(self) -> None:
        """A rectangle spanning two pages exists on neither, and a citation opening at
        it would land nowhere."""
        drafts = _chunk(
            [
                _element("alpha", page=1, order=0, box=BoundingBox(10, 700, 100, 720)),
                _element("beta", page=2, order=1, box=BoundingBox(10, 650, 120, 690)),
            ]
        )
        assert drafts[0].bounding_box is None

    def test_token_counts_are_recorded(self) -> None:
        drafts = _chunk([_element(_words(7))])
        assert drafts[0].token_count == 7


# ---------------------------------------------------------------------------
# Degenerate input
# ---------------------------------------------------------------------------


class TestDegenerateInput:
    def test_no_elements_yield_no_chunks(self) -> None:
        assert _chunk([]) == []

    def test_blank_elements_are_skipped(self) -> None:
        assert _chunk([_element("   "), _element("\n")]) == []

    def test_blank_elements_between_prose_do_not_split_it(self) -> None:
        drafts = _chunk(
            [_element("alpha", order=0), _element("  ", order=1), _element("beta", order=2)]
        )
        assert len(drafts) == 1
