"""create company

Revision ID: 0001
Revises:
Create Date: 2026-09-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "company",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("cik", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("fiscal_year_end_month", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("sic", sa.String(), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company")),
        sa.UniqueConstraint("ticker", name=op.f("uq_company_ticker")),
        sa.UniqueConstraint("cik", name=op.f("uq_company_cik")),
    )


def downgrade() -> None:
    op.drop_table("company")
