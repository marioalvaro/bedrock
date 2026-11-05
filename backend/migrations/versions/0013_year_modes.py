"""year modes: scenario_year_mode

A forecast year of the quarterly span is set either annually or by quarter, for a whole scenario
(docs/erd/forecasting.md "Year modes"). A missing row is `annual`. Backfill: every (scenario, year)
that holds a quarter row in any of its cases is `quarterly`. The downgrade drops the table; the
driver rows stay.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scenario_year_mode",
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.CheckConstraint(
            "mode IN ('annual', 'quarterly')", name=op.f("ck_scenario_year_mode_mode")
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenario.id"],
            name=op.f("fk_scenario_year_mode_scenario_id_scenario"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("scenario_id", "fiscal_year", name=op.f("pk_scenario_year_mode")),
    )
    op.execute(
        "INSERT INTO scenario_year_mode (scenario_id, fiscal_year, mode) "
        "SELECT DISTINCT c.scenario_id, d.fiscal_year, 'quarterly' "
        "FROM driver_value d JOIN scenario_case c ON c.id = d.case_id "
        "WHERE d.fiscal_period <> 'FY'"
    )


def downgrade() -> None:
    op.drop_table("scenario_year_mode")
