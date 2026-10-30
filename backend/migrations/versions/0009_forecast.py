"""forecast core: scenario, driver_value

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scenario",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("base_id", sa.Integer(), nullable=True),
        sa.Column("revenue_method", sa.String(), nullable=False),
        sa.Column("segment_dimension", sa.String(), nullable=True),
        sa.Column("volume_kpi", sa.String(), nullable=True),
        sa.Column("price_kpi", sa.String(), nullable=True),
        sa.Column("horizon_years", sa.Integer(), nullable=False),
        sa.Column("horizon_quarters", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(is_default = 1 AND base_id IS NULL) OR (is_default = 0 AND base_id IS NOT NULL)",
            name=op.f("ck_scenario_base"),
        ),
        sa.CheckConstraint(
            "revenue_method IN ('growth', 'segments', 'volume_price')",
            name=op.f("ck_scenario_revenue_method"),
        ),
        sa.CheckConstraint(
            "segment_dimension IN ('business', 'geo')", name=op.f("ck_scenario_segment_dimension")
        ),
        sa.CheckConstraint(
            "horizon_years BETWEEN 5 AND 10", name=op.f("ck_scenario_horizon_years")
        ),
        sa.CheckConstraint(
            "horizon_quarters BETWEEN 4 AND 8", name=op.f("ck_scenario_horizon_quarters")
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_scenario_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["base_id"],
            ["scenario.id"],
            name=op.f("fk_scenario_base_id_scenario"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario")),
        sa.UniqueConstraint("company_id", "name", name=op.f("uq_scenario_company_id")),
    )
    op.create_index(
        "uq_scenario_default",
        "scenario",
        ["company_id"],
        unique=True,
        sqlite_where=sa.text("is_default = 1"),
    )
    op.create_table(
        "driver_value",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("driver_code", sa.String(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("value", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("engine_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("fiscal_period = 'FY'", name=op.f("ck_driver_value_fiscal_period")),
        sa.CheckConstraint("kind IN ('value', 'offset')", name=op.f("ck_driver_value_kind")),
        sa.CheckConstraint("source IN ('manual', 'engine')", name=op.f("ck_driver_value_source")),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenario.id"],
            name=op.f("fk_driver_value_scenario_id_scenario"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_driver_value")),
        sa.UniqueConstraint(
            "scenario_id",
            "driver_code",
            "fiscal_year",
            "fiscal_period",
            name=op.f("uq_driver_value_scenario_id"),
        ),
    )


def downgrade() -> None:
    # The scenarios and their drivers are lost.
    op.drop_table("driver_value")
    op.drop_index("uq_scenario_default", table_name="scenario")
    op.drop_table("scenario")
