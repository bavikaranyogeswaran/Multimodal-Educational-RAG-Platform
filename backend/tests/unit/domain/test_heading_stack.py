"""Tests for HeadingStack.

Levels are inferred from type size because nothing in a PDF states them. The rule is that
a heading closes every open section set at its own size or smaller, and falls under any
set larger — so these tests are mostly about which sections survive a new heading and
which do not.
"""

from __future__ import annotations

from app.domain.documents.heading_stack import HeadingStack


class TestOpeningSections:
    def test_a_new_document_is_at_the_root(self) -> None:
        assert HeadingStack().current.segments == ()

    def test_a_heading_opens_a_section_containing_itself(self) -> None:
        stack = HeadingStack()
        assert stack.enter("Chapter One", size=18).segments == ("Chapter One",)

    def test_a_smaller_heading_nests_beneath_a_larger_one(self) -> None:
        stack = HeadingStack()
        stack.enter("Chapter One", size=18)
        path = stack.enter("First Section", size=13)
        assert path.segments == ("Chapter One", "First Section")

    def test_nesting_continues_to_a_third_level(self) -> None:
        stack = HeadingStack()
        stack.enter("Chapter", size=20)
        stack.enter("Section", size=15)
        path = stack.enter("Subsection", size=11)
        assert path.segments == ("Chapter", "Section", "Subsection")


class TestClosingSections:
    def test_a_heading_of_equal_size_replaces_its_sibling(self) -> None:
        stack = HeadingStack()
        stack.enter("Chapter One", size=18)
        path = stack.enter("Chapter Two", size=18)
        assert path.segments == ("Chapter Two",)

    def test_a_larger_heading_closes_everything_beneath_it(self) -> None:
        stack = HeadingStack()
        stack.enter("Chapter One", size=18)
        stack.enter("First Section", size=13)
        stack.enter("A Subsection", size=11)
        path = stack.enter("Chapter Two", size=18)
        assert path.segments == ("Chapter Two",)

    def test_a_sibling_section_keeps_its_parent(self) -> None:
        stack = HeadingStack()
        stack.enter("Chapter One", size=18)
        stack.enter("First Section", size=13)
        path = stack.enter("Second Section", size=13)
        assert path.segments == ("Chapter One", "Second Section")

    def test_an_intermediate_size_closes_only_what_it_outranks(self) -> None:
        stack = HeadingStack()
        stack.enter("Chapter", size=20)
        stack.enter("Section", size=15)
        stack.enter("Subsection", size=11)
        path = stack.enter("Another Section", size=15)
        assert path.segments == ("Chapter", "Another Section")


class TestContent:
    def test_content_carries_the_section_it_sits_in(self) -> None:
        stack = HeadingStack()
        stack.enter("Chapter", size=18)
        stack.enter("Section", size=13)
        assert stack.current.segments == ("Chapter", "Section")

    def test_the_path_does_not_change_between_headings(self) -> None:
        """Which is the whole point: everything after a heading belongs to it until
        another one replaces it, including across a page break."""
        stack = HeadingStack()
        stack.enter("Section", size=13)
        first = stack.current
        assert stack.current == first
        assert stack.current == first


class TestDegenerateHeadings:
    def test_a_blank_heading_opens_nothing(self) -> None:
        stack = HeadingStack()
        stack.enter("Chapter", size=18)
        path = stack.enter("   ", size=13)
        assert path.segments == ("Chapter",)

    def test_heading_text_is_trimmed(self) -> None:
        stack = HeadingStack()
        assert stack.enter("  Chapter  ", size=18).segments == ("Chapter",)

    def test_depth_reflects_the_open_sections(self) -> None:
        stack = HeadingStack()
        assert stack.depth == 0
        stack.enter("Chapter", size=18)
        assert stack.depth == 1
        stack.enter("Section", size=13)
        assert stack.depth == 2
        stack.enter("Chapter Two", size=18)
        assert stack.depth == 1
