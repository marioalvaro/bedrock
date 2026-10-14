"""analysis tables: adjustment, corporate_action, off_balance_item, qoe_threshold

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "adjustment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("canonical_code", sa.String(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_adjustment_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_adjustment")),
    )
    op.create_table(
        "corporate_action",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("ratio", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_corporate_action_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corporate_action")),
        sa.UniqueConstraint(
            "company_id", "effective_date", name=op.f("uq_corporate_action_company_id")
        ),
    )
    op.create_table(
        "off_balance_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("source_note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_off_balance_item_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_off_balance_item")),
    )
    op.create_table(
        "qoe_threshold",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_code", sa.String(), nullable=False),
        sa.Column("warn", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("alert", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_qoe_threshold")),
        sa.UniqueConstraint("rule_code", name=op.f("uq_qoe_threshold_rule_code")),
    )


def downgrade() -> None:
    op.drop_table("qoe_threshold")
    op.drop_table("off_balance_item")
    op.drop_table("corporate_action")
    op.drop_table("adjustment")
