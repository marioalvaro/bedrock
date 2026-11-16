"""filing-level XBRL (M7b S6): `filing_line`, `filing.xbrl_status` and `xbrl_parser_version`,
`raw_fact.source`

The lines on the face of each filing's three statements, with their calculation parents
(docs/erd/data-coverage.md "Storage"). `filing` and `raw_fact` only gain columns: SQLite's
ADD COLUMN, never a rebuild, so no row cascades away (G34). Existing facts become
`source = 'companyfacts'`, existing filings not tried (NULL). The downgrade drops only what this
revision added.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "filing",
        sa.Column(
            "xbrl_status",
            sa.String(),
            sa.CheckConstraint(
                "xbrl_status IN ('parsed', 'absent', 'failed')", name="ck_filing_xbrl_status"
            ),
            nullable=True,
        ),
    )
    op.add_column("filing", sa.Column("xbrl_parser_version", sa.Integer(), nullable=True))
    op.add_column(
        "raw_fact",
        sa.Column(
            "source",
            sa.String(),
            sa.CheckConstraint("source IN ('companyfacts', 'filing')", name="ck_raw_fact_source"),
            nullable=False,
            server_default="companyfacts",
        ),
    )
    op.create_table(
        "filing_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "filing_id",
            sa.Integer(),
            sa.ForeignKey("filing.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("statement", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("taxonomy", sa.String(), nullable=False),
        sa.Column("concept", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("calc_parent_taxonomy", sa.String(), nullable=True),
        sa.Column("calc_parent_concept", sa.String(), nullable=True),
        sa.Column("calc_weight", sa.Numeric(28, 10), nullable=True),
        sa.UniqueConstraint("filing_id", "statement", "taxonomy", "concept"),
        sa.CheckConstraint("statement IN ('IS', 'BS', 'CF')", name="ck_filing_line_statement"),
    )
    op.create_index("ix_filing_line_filing_id", "filing_line", ["filing_id"])


def downgrade() -> None:
    """SQLite's DROP COLUMN refuses a column with a CHECK constraint, so the batch mode copies
    `raw_fact` and `filing`, and dropping the old `filing` would cascade to its facts. The pragma
    is a no-op once a statement has opened a transaction, so it runs first (G34)."""
    op.execute("PRAGMA foreign_keys=OFF")
    op.drop_index("ix_filing_line_filing_id", table_name="filing_line")
    op.drop_table("filing_line")
    with op.batch_alter_table("raw_fact") as batch:
        batch.drop_constraint("ck_raw_fact_source", type_="check")
        batch.drop_column("source")
    with op.batch_alter_table("filing") as batch:
        batch.drop_constraint("ck_filing_xbrl_status", type_="check")
        batch.drop_column("xbrl_parser_version")
        batch.drop_column("xbrl_status")
