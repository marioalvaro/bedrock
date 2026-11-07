"""market series: macro_series, macro_observation

The stored market data behind the valuation's market defaults: the risk-free rate, the Damodaran
implied ERP and the S&P 500 monthly closes (docs/erd/data.md; the M8 FRED series reuse the same
tables). The downgrade drops both tables.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "macro_series",
        sa.Column("series_id", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("frequency", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("series_id", name=op.f("pk_macro_series")),
    )
    op.create_table(
        "macro_observation",
        sa.Column("series_id", sa.String(length=40), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["macro_series.series_id"],
            name=op.f("fk_macro_observation_series_id_macro_series"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("series_id", "date", name=op.f("pk_macro_observation")),
    )


def downgrade() -> None:
    op.drop_table("macro_observation")
    op.drop_table("macro_series")
