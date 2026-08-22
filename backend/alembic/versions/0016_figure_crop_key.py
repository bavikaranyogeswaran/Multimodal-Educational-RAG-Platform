"""Add crop_key to document_figures.

After step 6.5 lands, every figure detected during ingestion has its page rendered,
cropped to its bounding box, and uploaded to R2. The R2 key is stored here so Phase
6.7 can retrieve the image without re-rendering and re-uploading it.

The column is nullable: records from documents processed before this step have no
crop, and records where the page failed to render during ingestion also have no crop.
Both are valid; Phase 6.7 can treat a null crop_key as a signal to re-run cropping
rather than image analysis.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_figures", sa.Column("crop_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_figures", "crop_key")
