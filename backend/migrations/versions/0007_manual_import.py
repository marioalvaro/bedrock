"""manual import: statement_import, imported_fact, custom_line

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "statement_import",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("format", sa.String(), nullable=False),
        sa.Column("scale", sa.String(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.Column("cells", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.CheckConstraint("format IN ('xlsx', 'csv')", name=op.f("ck_statement_import_format")),
        sa.CheckConstraint(
            "scale IN ('units', 'thousands', 'millions', 'billions')",
            name=op.f("ck_statement_import_scale"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_statement_import_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_statement_import")),
    )
    op.create_index("ix_statement_import_company_id", "statement_import", ["company_id"])
    op.create_table(
        "imported_fact",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("import_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("line_code", sa.String(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period", sa.String(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.CheckConstraint(
            "fiscal_period IN ('FY', 'Q1', 'Q2', 'Q3', 'Q4')",
            name=op.f("ck_imported_fact_fiscal_period"),
        ),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["statement_import.id"],
            name=op.f("fk_imported_fact_import_id_statement_import"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_imported_fact_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_imported_fact")),
        sa.UniqueConstraint(
            "import_id",
            "line_code",
            "fiscal_year",
            "fiscal_period",
            name=op.f("uq_imported_fact_import_id"),
        ),
    )
    op.create_index(
        "ix_imported_fact_company_line",
        "imported_fact",
        ["company_id", "line_code", "fiscal_year", "fiscal_period"],
    )
    op.create_table(
        "custom_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("statement", sa.String(), nullable=False),
        sa.Column("parent_code", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("children_complete", sa.Boolean(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "statement IN ('IS', 'BS', 'CF')", name=op.f("ck_custom_line_statement")
        ),
        sa.CheckConstraint(
            "kind IN ('flow', 'instant', 'average')", name=op.f("ck_custom_line_kind")
        ),
        sa.CheckConstraint(
            "unit IN ('USD', 'USD/shares', 'shares')", name=op.f("ck_custom_line_unit")
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_custom_line_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_line")),
        sa.UniqueConstraint("company_id", "code", name=op.f("uq_custom_line_company_id")),
    )


def downgrade() -> None:
    # The imported values and custom lines are lost.
    op.drop_table("custom_line")
    op.drop_index("ix_imported_fact_company_line", table_name="imported_fact")
    op.drop_table("imported_fact")
    op.drop_index("ix_statement_import_company_id", table_name="statement_import")
    op.drop_table("statement_import")
