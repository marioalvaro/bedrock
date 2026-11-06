"""driver engines: driver_engine_choice

The forecast engine a scenario uses for one driver's default, shared by its three cases
(docs/erd/forecasting.md "Statistical engines (M6)"). Only non-`auto` choices are stored. The
downgrade drops the table.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "driver_engine_choice",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("driver_code", sa.String(length=80), nullable=False),
        sa.Column("engine_code", sa.String(length=10), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "engine_code IN ('mean', 'arima', 'ets', 'blend', 'stl')",
            name=op.f("ck_driver_engine_choice_engine_code"),
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenario.id"],
            name=op.f("fk_driver_engine_choice_scenario_id_scenario"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_driver_engine_choice")),
        sa.UniqueConstraint(
            "scenario_id", "driver_code", name=op.f("uq_driver_engine_choice_scenario_id")
        ),
    )


def downgrade() -> None:
    op.drop_table("driver_engine_choice")
