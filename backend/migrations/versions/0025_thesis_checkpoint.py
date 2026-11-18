"""thesis checkpoints (M7c S3): `thesis_checkpoint`

A company's testable thesis statements (docs/erd/workspace.md "Thesis checkpoints"). A new table
only: nothing is rebuilt (G34). Their state is computed on read, so no state column.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "thesis_checkpoint",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("statement", sa.String(), nullable=False),
        sa.Column("freq", sa.String(), nullable=False),
        sa.Column("margin", sa.Numeric(28, 10), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("freq IN ('annual', 'ttm')", name="ck_thesis_checkpoint_freq"),
        sa.CheckConstraint("margin IS NULL OR margin >= 0", name="ck_thesis_checkpoint_margin"),
    )
    op.create_index("ix_thesis_checkpoint_company_id", "thesis_checkpoint", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_thesis_checkpoint_company_id", table_name="thesis_checkpoint")
    op.drop_table("thesis_checkpoint")
