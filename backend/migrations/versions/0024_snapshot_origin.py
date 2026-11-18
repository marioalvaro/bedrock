"""snapshot origin (M7c S2): `forecast_snapshot.origin` and `trigger_accession`

An automatic snapshot is taken by the refresh just before it stores a new 10-K or 10-Q
(docs/erd/accountability.md "Automatic snapshots"); `trigger_accession` names that filing.
Existing rows become `manual`. ADD COLUMN only, never a table rebuild (G34): SQLite accepts the
column's CHECK in ADD COLUMN, and drops it with the column.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Raw SQL: Alembic's add_column does not render a column-level CHECK.
    op.execute(
        "ALTER TABLE forecast_snapshot ADD COLUMN origin VARCHAR DEFAULT 'manual' NOT NULL "
        "CONSTRAINT ck_forecast_snapshot_origin CHECK (origin IN ('manual', 'auto'))"
    )
    op.add_column("forecast_snapshot", sa.Column("trigger_accession", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("forecast_snapshot", "trigger_accession")
    op.drop_column("forecast_snapshot", "origin")
