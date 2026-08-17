"""Track which section each element sits in, as a document is read through.

A heading applies to everything after it until a heading of the same or greater standing
replaces it. Nothing in a PDF says so — headings carry no level, only a size — so the
hierarchy is inferred from the sizes themselves: a smaller heading falls under the larger
one above it, and an equal or larger one closes it.

The state is a document's, not a page's. A section that begins near the foot of one page
continues onto the next, and a stack rebuilt per page would lose that at every break —
which is the one place it matters most, because a chunk at the top of a page has the least
context of its own to fall back on.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.values import HeadingPath


@dataclass(frozen=True, slots=True)
class _Level:
    size: float
    text: str


class HeadingStack:
    """The open sections at a point in a document, outermost first.

    Mutable by design: it is read through a document once, in order, and each element
    asks it where it currently is.
    """

    def __init__(self) -> None:
        self._levels: list[_Level] = []

    @property
    def current(self) -> HeadingPath:
        path = HeadingPath.root()
        for level in self._levels:
            path = path.child(level.text)
        return path

    def enter(self, heading: str, *, size: float) -> HeadingPath:
        """Open a section, closing any it supersedes, and return the resulting path.

        Sections at the same size or smaller are closed first. Equal size means a sibling
        — the next section at the same standing — and smaller means a subsection of
        something that has now ended. Only a heading set larger than this one survives,
        because only that one still contains it.
        """
        text = heading.strip()
        if not text:
            return self.current

        while self._levels and self._levels[-1].size <= size:
            self._levels.pop()
        self._levels.append(_Level(size=size, text=text))
        return self.current

    @property
    def depth(self) -> int:
        return len(self._levels)
