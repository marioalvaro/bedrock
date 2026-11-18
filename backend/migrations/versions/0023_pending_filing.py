"""pending filings (M7c S1): `pending_filing` and `company.filings_checked_at`

The 10-Ks and 10-Qs EDGAR's filing index lists that `filing` does not hold yet, found by the
daily check (docs/erd/data.md "New-filing detection"). `company` only gains a column: SQLite's
ADD COLUMN, never a rebuild, so no row cascades away (G34).

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("company", sa.Column("filings_checked_at", sa.DateTime(), nullable=True))
    op.create_table(
        "pending_filing",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("accession_no", sa.String(), nullable=False, unique=True),
        sa.Column("form", sa.String(), nullable=False),
        sa.Column("filed_at", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("form IN ('10-K', '10-Q')", name="ck_pending_filing_form"),
    )
    op.create_index("ix_pending_filing_company_id", "pending_filing", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_pending_filing_company_id", table_name="pending_filing")
    op.drop_table("pending_filing")
    op.drop_column("company", "filings_checked_at")
