"""Let a citation outlive the chunk it points at.

Reading a document again replaces its chunks: the parser gives every element a new
identity on each run, so the old rows are deleted and new ones written in their place.
Under `ON DELETE CASCADE` that deletion reached through `chunk_id` and took the citations
with it, so re-reading one document erased the sources of every answer already given
about it. The answers survived; what they rested on did not, which turns a conversation
into a set of claims with no attribution.

The table was already built for this. Location, type and the evidence hash are stored
here as copies rather than read through `chunk_id`, precisely so a citation still means
something after the passage it names has been rewritten. The foreign key was the one part
that had not been told.

`chunk_id` becomes nullable and clears on delete. Null records that the exact passage is
no longer stored — the page, the region and the hash of what it said are still beside it,
so the citation can still be read and still points at the right part of the document.

Deleting the document itself is untouched and still cascades. There the source really is
gone, and a citation into it would name a page nobody can open.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Postgres names an unnamed foreign key `{table}_{column}_fkey`, and 0009 created this
#: one inline without a name of its own.
_FK = "message_citations_chunk_id_fkey"


def upgrade() -> None:
    op.execute(f"ALTER TABLE message_citations DROP CONSTRAINT IF EXISTS {_FK}")
    op.alter_column(
        "message_citations",
        "chunk_id",
        existing_type=sa.Uuid(as_uuid=True),
        nullable=True,
    )
    op.create_foreign_key(
        _FK,
        "message_citations",
        "chunks",
        ["chunk_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Rows whose chunk has already gone cannot be made NOT NULL again, and there is
    # nothing to restore them to — the passage they named no longer exists. They are
    # deleted, which is exactly what the constraint being restored would have done to
    # them at the moment their chunk was removed.
    op.execute("DELETE FROM message_citations WHERE chunk_id IS NULL")
    op.execute(f"ALTER TABLE message_citations DROP CONSTRAINT IF EXISTS {_FK}")
    op.alter_column(
        "message_citations",
        "chunk_id",
        existing_type=sa.Uuid(as_uuid=True),
        nullable=False,
    )
    op.create_foreign_key(
        _FK,
        "message_citations",
        "chunks",
        ["chunk_id"],
        ["id"],
        ondelete="CASCADE",
    )
