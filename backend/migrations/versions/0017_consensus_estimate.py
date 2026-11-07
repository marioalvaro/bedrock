"""consensus: consensus_estimate

Yahoo's analyst consensus per company, relative period and metric, logged as guidance
(docs/erd/analysis.md "Consensus guidance"). The downgrade drops the table.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consensus_estimate",
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(length=4), nullable=False),
        sa.Column("metric", sa.String(length=10), nullable=False),
        sa.Column("low", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("avg", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("high", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("analysts", sa.Integer(), nullable=True),
        sa.Column("year_ago_revenue", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_consensus_estimate_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "company_id", "period", "metric", name=op.f("pk_consensus_estimate")
        ),
    )


def downgrade() -> None:
    op.drop_table("consensus_estimate")
