"""A table lifted off a page as a structured object rather than a run of prose.

Parsing records that a table exists, where it sits, and what its cells say, joined
into one string. That is enough to keep the numbers out of the surrounding paragraphs
but not enough to answer a question about them: "what is the density of aluminium"
needs to know which column is density and which row is aluminium, and a joined string
has thrown that away.

What this module adds is the grid — which row names the columns, what unit each column
is measured in, and what the remaining rows hold — so a table can be retrieved and cited
as a table.

Cells stay plain strings while the caption is `UntrustedText`, and the split is
deliberate. Both came out of a student's file, so neither can be trusted, but they fail
differently when handled carelessly. A caption is a sentence: dropped into a prompt
template it reads as prose and whatever it tells the model to do arrives looking like
instruction. A grid is not a sentence, and interpolating one yields visibly broken
output rather than a fluent lie. The rendered forms built on top of this grid are
sentences again, and carry the untrusted type accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from app.domain.errors import InvariantViolationError
from app.domain.invariants import (
    require_positive,
    require_timezone_aware,
    require_within,
)
from app.domain.scope import ScopeContext
from app.domain.values import BoundingBox, UntrustedText


@dataclass(frozen=True, slots=True)
class DocumentTable:
    """One table on one page, with its columns named and its rows aligned to them.

    Every row is the same width as `headers`. Ragged input is squared off before it
    reaches here, because a row that is short by one cell has silently shifted every
    value after the gap into the wrong column, and a table that answers confidently
    with the wrong column is worse than one that admits it could not be read.
    """

    id: UUID
    user_id: UUID
    knowledge_base_id: UUID
    document_id: UUID
    source_element_id: UUID
    page_number: int
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    bounding_box: BoundingBox
    created_at: datetime

    # One entry per column, aligned to `headers`, holding the unit that column is
    # measured in where the document stated one. Absent for a column that carries no
    # unit, which is most of them — a name or a category has nothing to measure.
    units: tuple[str | None, ...] = ()

    # The document's own words about the table, when it labelled one. Kept whole, with
    # the number below extracted from it rather than removed — a caption reads as the
    # document wrote it, and the number is what a reference resolves against.
    caption: UntrustedText | None = None

    # The number the document gave this table, as it was written: "4.2", "A.1", "3".
    # A student refers to a table by this, so it is stored as data rather than left
    # inside a sentence where only a substring search could reach it.
    number: str | None = None

    # How much of the detected region actually read as a table. Detection is heuristic
    # and a page of aligned prose can look like one, so a reader downstream needs to be
    # able to weigh this rather than assume every detection is equally sound.
    confidence: float | None = None

    # The serialised forms, attached after the grid is read. Stored rather than derived
    # on demand: the prose form is what gets embedded, and a vector only means anything
    # against the exact text it was built from. Re-rendering with a changed renderer
    # would leave stored vectors describing text that no longer exists.
    table_json: str | None = None
    markdown: str | None = None
    html: str | None = None
    embedding_text: str | None = None

    def __post_init__(self) -> None:
        require_positive(self.page_number, "DocumentTable.page_number")
        require_timezone_aware(self.created_at, "DocumentTable.created_at")

        if self.confidence is not None:
            require_within(self.confidence, "DocumentTable.confidence", low=0.0, high=1.0)

        if not self.headers:
            raise InvariantViolationError(
                "a table must name its columns — rows without headers cannot be read back"
            )

        width = len(self.headers)

        if self.units and len(self.units) != width:
            raise InvariantViolationError(
                f"units must line up with headers: {len(self.units)} units, {width} columns"
            )

        for index, row in enumerate(self.rows):
            if len(row) != width:
                raise InvariantViolationError(
                    f"row {index} has {len(row)} cells against {width} columns — "
                    "a row that does not line up puts values under the wrong headings"
                )

    @property
    def scope(self) -> ScopeContext:
        return ScopeContext(user_id=self.user_id, knowledge_base_id=self.knowledge_base_id)

    @property
    def is_rendered(self) -> bool:
        """Whether the serialised forms have been attached yet."""
        return self.embedding_text is not None

    def with_renderings(
        self,
        *,
        table_json: str,
        markdown: str,
        html: str,
        embedding_text: str,
    ) -> DocumentTable:
        """Attach the serialised forms, returning a new table.

        Separate from construction because rendering is its own concern with its own
        rules, and the parser that builds the grid has no business knowing what Markdown
        looks like.
        """
        return replace(
            self,
            table_json=table_json,
            markdown=markdown,
            html=html,
            embedding_text=embedding_text,
        )

    @property
    def column_count(self) -> int:
        return len(self.headers)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def is_empty(self) -> bool:
        """Whether the table has headers but nothing under them.

        A detected region that yielded no data rows is still worth recording — it marks
        a place on the page a student can point at — but it has nothing to answer with.
        """
        return not self.rows

    def unit_for(self, header: str) -> str | None:
        """The unit belonging to a named column, or None if it has none or is unknown."""
        try:
            index = self.headers.index(header)
        except ValueError:
            return None
        if index >= len(self.units):
            return None
        return self.units[index]

    def column(self, header: str) -> tuple[str, ...]:
        """Every value under a named column, top to bottom.

        Raises rather than returning empty for a name that is not a column, because a
        silent empty result reads as "this column is blank" when it means "you asked
        for a column that does not exist".
        """
        try:
            index = self.headers.index(header)
        except ValueError as exc:
            raise InvariantViolationError(
                f"no column named {header!r}; the table has {list(self.headers)}"
            ) from exc
        return tuple(row[index] for row in self.rows)
