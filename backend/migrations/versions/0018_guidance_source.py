"""guidance: source (management | consensus)

Consensus guidance (docs/erd/analysis.md "Consensus guidance"): the daily consensus refresh logs
analysts' ranges as guidance entries, told apart from management's by `source`. Existing entries
are management guidance. The downgrade drops the column and keeps every row.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("guidance") as batch:
        batch.add_column(
            sa.Column("source", sa.String(), nullable=False, server_default="management")
        )
        batch.create_check_constraint(
            op.f("ck_guidance_source"), "source IN ('management', 'consensus')"
        )


def downgrade() -> None:
    with op.batch_alter_table("guidance") as batch:
        batch.drop_constraint(op.f("ck_guidance_source"), type_="check")
        batch.drop_column("source")
