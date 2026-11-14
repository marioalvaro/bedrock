"""mapping weight and covers: signed members (M7b S3) and combined lines (M7b S4)

`concept_mapping.weight` is +1, or -1 for a subtracted member of a summed concept; `covers` lists,
for a combined entry, the canonical codes inside it (docs/erd/data-coverage.md "Mapping
language"). Existing rows become plain added members (weight 1, covers null). The downgrade drops
only the two columns.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("concept_mapping") as batch:
        batch.add_column(sa.Column("weight", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("covers", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("concept_mapping") as batch:
        batch.drop_column("covers")
        batch.drop_column("weight")
