"""custom QoE rules and formula levels: qoe_custom_rule, qoe_threshold.*_formula

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "qoe_custom_rule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("formula", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("warn", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("alert", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("warn_formula", sa.String(), nullable=True),
        sa.Column("alert_formula", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "direction IN ('above', 'below')", name=op.f("ck_qoe_custom_rule_direction")
        ),
        sa.CheckConstraint("unit IN ('pct', 'x')", name=op.f("ck_qoe_custom_rule_unit")),
        sa.CheckConstraint(
            "warn IS NULL OR warn_formula IS NULL",
            name=op.f("ck_qoe_custom_rule_warn_number_or_formula"),
        ),
        sa.CheckConstraint(
            "alert IS NULL OR alert_formula IS NULL",
            name=op.f("ck_qoe_custom_rule_alert_number_or_formula"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_qoe_custom_rule")),
    )
    with op.batch_alter_table("qoe_threshold") as batch:
        batch.add_column(sa.Column("warn_formula", sa.String(), nullable=True))
        batch.add_column(sa.Column("alert_formula", sa.String(), nullable=True))
        batch.create_check_constraint(
            op.f("ck_qoe_threshold_warn_number_or_formula"),
            "warn IS NULL OR warn_formula IS NULL",
        )
        batch.create_check_constraint(
            op.f("ck_qoe_threshold_alert_number_or_formula"),
            "alert IS NULL OR alert_formula IS NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("qoe_threshold") as batch:
        batch.drop_constraint(op.f("ck_qoe_threshold_alert_number_or_formula"), type_="check")
        batch.drop_constraint(op.f("ck_qoe_threshold_warn_number_or_formula"), type_="check")
        batch.drop_column("alert_formula")
        batch.drop_column("warn_formula")
    op.drop_table("qoe_custom_rule")
