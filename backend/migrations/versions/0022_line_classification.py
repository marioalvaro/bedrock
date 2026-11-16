"""line classification (M7d S3): `line_classification`, `classification_run`, the company's mode
and source, the snapshot's mode

A classifier's answers for the face lines nothing classifies, as proposals the user decides on,
and the runs that produced them (docs/erd/face-tree.md "Storage"). `company` and
`forecast_snapshot` only gain columns: SQLite's ADD COLUMN, never a rebuild, so no row cascades
away (G34). Every company starts with the layer `off`; an existing snapshot does not know its
mode (NULL). The new columns carry no CHECK, so the downgrade drops them in place.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "company",
        sa.Column("classification_mode", sa.String(), nullable=False, server_default="off"),
    )
    op.add_column("company", sa.Column("classification_source", sa.String(), nullable=True))
    op.add_column("forecast_snapshot", sa.Column("classification_mode", sa.String(), nullable=True))
    op.create_table(
        "classification_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("classifier", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("lines_asked", sa.Integer(), nullable=False),
        sa.Column("lines_answered", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'done', 'failed', 'stopped')",
            name="ck_classification_run_status",
        ),
    )
    op.create_index("ix_classification_run_company_id", "classification_run", ["company_id"])
    op.create_index("ix_classification_run_started_at", "classification_run", ["started_at"])
    # one running row in the whole database
    op.create_index(
        "uq_classification_run_running",
        "classification_run",
        ["status"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
    )
    op.create_table(
        "line_classification",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("company.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("statement", sa.String(), nullable=False),
        sa.Column("taxonomy", sa.String(), nullable=False),
        sa.Column("concept", sa.String(), nullable=False),
        sa.Column("classifier", sa.String(), nullable=False),
        sa.Column("codes", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(6, 4), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("classification_run.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("company_id", "statement", "taxonomy", "concept", "classifier"),
        sa.CheckConstraint(
            "statement IN ('IS', 'BS', 'CF')", name="ck_line_classification_statement"
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected')",
            name="ck_line_classification_status",
        ),
    )
    op.create_index("ix_line_classification_company_id", "line_classification", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_line_classification_company_id", table_name="line_classification")
    op.drop_table("line_classification")
    op.drop_index("uq_classification_run_running", table_name="classification_run")
    op.drop_index("ix_classification_run_started_at", table_name="classification_run")
    op.drop_index("ix_classification_run_company_id", table_name="classification_run")
    op.drop_table("classification_run")
    op.drop_column("forecast_snapshot", "classification_mode")
    op.drop_column("company", "classification_source")
    op.drop_column("company", "classification_mode")
