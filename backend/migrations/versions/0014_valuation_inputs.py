"""valuation inputs: valuation_input

The valuation inputs a scenario case sets itself, as text (docs/erd/valuation.md "Tables"). A
missing row inherits. The downgrade drops the table.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "valuation_input",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("value", sa.String(length=40), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["scenario_case.id"],
            name=op.f("fk_valuation_input_case_id_scenario_case"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_valuation_input")),
        sa.UniqueConstraint("case_id", "code", name=op.f("uq_valuation_input_case_id")),
    )


def downgrade() -> None:
    op.drop_table("valuation_input")
