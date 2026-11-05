"""fixed forecast horizon: drop scenario.horizon_years and scenario.horizon_quarters

Every scenario forecasts 5 years and 8 quarters (user decision 2026-10-31), so the per-scenario
horizon columns go.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIXED_YEARS = 5
FIXED_QUARTERS = 8


def _rebuild_without_cascades() -> None:
    """Rebuilding `scenario` drops the old table, and with foreign keys on SQLite then deletes
    every driver row and every non-base scenario (both cascade from it, G34). The pragma is a
    no-op once a statement has opened a transaction, so this runs before anything else."""
    op.execute("PRAGMA foreign_keys=OFF")


def upgrade() -> None:
    _rebuild_without_cascades()
    with op.batch_alter_table("scenario") as batch:
        batch.drop_constraint(op.f("ck_scenario_horizon_years"), type_="check")
        batch.drop_constraint(op.f("ck_scenario_horizon_quarters"), type_="check")
        batch.drop_column("horizon_years")
        batch.drop_column("horizon_quarters")


def downgrade() -> None:
    _rebuild_without_cascades()
    with op.batch_alter_table("scenario") as batch:
        batch.add_column(
            sa.Column(
                "horizon_years", sa.Integer(), nullable=False, server_default=str(FIXED_YEARS)
            )
        )
        batch.add_column(
            sa.Column(
                "horizon_quarters",
                sa.Integer(),
                nullable=False,
                server_default=str(FIXED_QUARTERS),
            )
        )
        batch.create_check_constraint(
            op.f("ck_scenario_horizon_years"), "horizon_years BETWEEN 5 AND 10"
        )
        batch.create_check_constraint(
            op.f("ck_scenario_horizon_quarters"), "horizon_quarters BETWEEN 4 AND 8"
        )
