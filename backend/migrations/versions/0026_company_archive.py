"""company archive (M7c S6): `company.archived_at`

An archived company is kept with all its data but leaves the followed list and the scheduler;
it is deleted permanently only once archived (docs/erd/workspace.md "Archive and permanent
deletion"). ADD COLUMN only, never a rebuild of `company`, so no row cascades away (G34).

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("company", sa.Column("archived_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("company", "archived_at")
