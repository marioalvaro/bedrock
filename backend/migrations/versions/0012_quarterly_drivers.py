"""quarterly drivers: driver_value.fiscal_period may be Q1..Q4

A driver can be set for one forecast quarter (docs/erd/forecasting.md "Quarterly drivers"), so the
fiscal_period check widens from `FY` to `FY` and the four quarters. `driver_value` is referenced
by no table, so the batch rebuild cascades nothing (G34). The downgrade deletes the quarter rows
first: the old check would reject them.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-01

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = op.f("ck_driver_value_fiscal_period")


def upgrade() -> None:
    with op.batch_alter_table("driver_value") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, "fiscal_period IN ('FY', 'Q1', 'Q2', 'Q3', 'Q4')")


def downgrade() -> None:
    op.execute("DELETE FROM driver_value WHERE fiscal_period <> 'FY'")
    with op.batch_alter_table("driver_value") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.create_check_constraint(CHECK, "fiscal_period = 'FY'")
