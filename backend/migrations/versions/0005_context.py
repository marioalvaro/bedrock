"""context tables: segment_series, segment_value, comps_set, comps_member, guidance, note

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERIODS = "('FY', 'Q1', 'Q2', 'Q3', 'Q4')"


def upgrade() -> None:
    op.create_table(
        "segment_series",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("dimension", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "dimension IN ('business', 'geo', 'kpi')", name=op.f("ck_segment_series_dimension")
        ),
        sa.CheckConstraint(
            "unit IN ('USD', 'pct', 'count', 'USD_per_unit')",
            name=op.f("ck_segment_series_unit"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_segment_series_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_segment_series")),
        sa.UniqueConstraint(
            "company_id",
            "dimension",
            "name",
            "metric",
            name=op.f("uq_segment_series_company_id"),
        ),
    )
    op.create_table(
        "segment_value",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period", sa.String(), nullable=False),
        sa.Column("value", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            f"fiscal_period IN {_PERIODS}", name=op.f("ck_segment_value_fiscal_period")
        ),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["segment_series.id"],
            name=op.f("fk_segment_value_series_id_segment_series"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_segment_value")),
        sa.UniqueConstraint(
            "series_id", "fiscal_year", "fiscal_period", name=op.f("uq_segment_value_series_id")
        ),
    )
    op.create_table(
        "comps_set",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_comps_set_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comps_set")),
        sa.UniqueConstraint("company_id", "name", name=op.f("uq_comps_set_company_id")),
    )
    op.create_table(
        "comps_member",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("comps_set_id", sa.Integer(), nullable=False),
        sa.Column("peer_company_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["comps_set_id"],
            ["comps_set.id"],
            name=op.f("fk_comps_member_comps_set_id_comps_set"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["peer_company_id"],
            ["company.id"],
            name=op.f("fk_comps_member_peer_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comps_member")),
        sa.UniqueConstraint(
            "comps_set_id", "peer_company_id", name=op.f("uq_comps_member_comps_set_id")
        ),
    )
    op.create_table(
        "guidance",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period", sa.String(), nullable=False),
        sa.Column("low", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("high", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("basis", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("given_on", sa.Date(), nullable=False),
        sa.Column("source_note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("low <= high", name=op.f("ck_guidance_low_le_high")),
        sa.CheckConstraint(f"fiscal_period IN {_PERIODS}", name=op.f("ck_guidance_fiscal_period")),
        sa.CheckConstraint("basis IN ('reported', 'normalized')", name=op.f("ck_guidance_basis")),
        sa.CheckConstraint("direction IN ('higher', 'lower')", name=op.f("ck_guidance_direction")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_guidance_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guidance")),
    )
    op.create_table(
        "note",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("body_md", sa.String(), nullable=False),
        sa.Column("canonical_code", sa.String(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("fiscal_period", sa.String(), nullable=True),
        sa.Column("note_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(fiscal_year IS NULL) = (fiscal_period IS NULL)",
            name=op.f("ck_note_period_both_or_none"),
        ),
        sa.CheckConstraint(
            f"fiscal_period IS NULL OR fiscal_period IN {_PERIODS}",
            name=op.f("ck_note_fiscal_period"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_note_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_note")),
    )
    op.create_index(
        "uq_segment_series_kpi_code",
        "segment_series",
        ["company_id", "metric"],
        unique=True,
        sqlite_where=sa.text("dimension = 'kpi'"),
    )
    op.create_index(op.f("ix_comps_member_peer_company_id"), "comps_member", ["peer_company_id"])
    op.create_index(op.f("ix_guidance_company_id"), "guidance", ["company_id"])
    op.create_index(op.f("ix_note_company_id"), "note", ["company_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_note_company_id"), table_name="note")
    op.drop_index(op.f("ix_guidance_company_id"), table_name="guidance")
    op.drop_index(op.f("ix_comps_member_peer_company_id"), table_name="comps_member")
    op.drop_index("uq_segment_series_kpi_code", table_name="segment_series")
    op.drop_table("note")
    op.drop_table("guidance")
    op.drop_table("comps_member")
    op.drop_table("comps_set")
    op.drop_table("segment_value")
    op.drop_table("segment_series")
