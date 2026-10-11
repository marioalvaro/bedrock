"""data layer: filing, raw_fact, canonical_item, concept_mapping, price_daily

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "filing",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("accession_no", sa.String(), nullable=False),
        sa.Column("form", sa.String(), nullable=False),
        sa.Column("filed_at", sa.Date(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("fiscal_period", sa.String(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_filing_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_filing")),
        sa.UniqueConstraint("accession_no", name=op.f("uq_filing_accession_no")),
    )
    op.create_table(
        "canonical_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("statement", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("sign", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("parent_code", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_canonical_item")),
        sa.UniqueConstraint("code", name=op.f("uq_canonical_item_code")),
    )
    op.create_table(
        "raw_fact",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("filing_id", sa.Integer(), nullable=False),
        sa.Column("taxonomy", sa.String(), nullable=False),
        sa.Column("concept", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("fiscal_period", sa.String(), nullable=True),
        sa.Column("frame", sa.String(), nullable=True),
        sa.Column("value", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_raw_fact_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["filing_id"],
            ["filing.id"],
            name=op.f("fk_raw_fact_filing_id_filing"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_fact")),
        sa.UniqueConstraint(
            "filing_id",
            "taxonomy",
            "concept",
            "unit",
            "period_start",
            "period_end",
            name=op.f("uq_raw_fact_filing_id"),
        ),
    )
    op.create_index(
        "ix_raw_fact_company_concept",
        "raw_fact",
        ["company_id", "taxonomy", "concept"],
        unique=False,
    )
    op.create_table(
        "concept_mapping",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("canonical_code", sa.String(), nullable=False),
        sa.Column("taxonomy", sa.String(), nullable=False),
        sa.Column("concept", sa.String(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["canonical_code"],
            ["canonical_item.code"],
            name=op.f("fk_concept_mapping_canonical_code_canonical_item"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_concept_mapping_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_concept_mapping")),
    )
    op.create_table(
        "price_daily",
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("adj_close", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_price_daily_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("company_id", "date", name=op.f("pk_price_daily")),
    )


def downgrade() -> None:
    op.drop_table("price_daily")
    op.drop_table("concept_mapping")
    op.drop_index("ix_raw_fact_company_concept", table_name="raw_fact")
    op.drop_table("raw_fact")
    op.drop_table("canonical_item")
    op.drop_table("filing")
