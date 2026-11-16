"""accountability: stored snapshots, backtest runs and the audit log

forecast_snapshot, forecast_run, forecast_value, valuation_run and audit_log
(docs/erd/accountability.md "Tables"), and the index on filing.company_id that the point-in-time
history's filing queries filter on. The downgrade drops only those.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NUMBER = sa.Numeric(precision=28, scale=10)


def upgrade() -> None:
    op.create_index("ix_filing_company_id", "filing", ["company_id"])
    op.create_table(
        "forecast_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=True),
        sa.Column("scenario_name", sa.String(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("data_as_of", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_forecast_snapshot_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenario.id"],
            name=op.f("fk_forecast_snapshot_scenario_id_scenario"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecast_snapshot")),
    )
    op.create_index(
        "ix_forecast_snapshot_company_created", "forecast_snapshot", ["company_id", "created_at"]
    )
    op.create_table(
        "forecast_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=True),
        sa.Column("case", sa.String(length=4), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("engines_json", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint("kind IN ('snapshot', 'backtest')", name=op.f("ck_forecast_run_kind")),
        sa.CheckConstraint(
            "\"case\" IN ('base', 'bull', 'bear')", name=op.f("ck_forecast_run_case")
        ),
        sa.CheckConstraint(
            "(kind = 'snapshot' AND snapshot_id IS NOT NULL AND \"case\" IS NOT NULL) "
            "OR (kind = 'backtest' AND method IS NOT NULL)",
            name=op.f("ck_forecast_run_kind_columns"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_forecast_run_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["forecast_snapshot.id"],
            name=op.f("fk_forecast_run_snapshot_id_forecast_snapshot"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecast_run")),
        sa.UniqueConstraint("snapshot_id", "case", name=op.f("uq_forecast_run_snapshot_id")),
        sa.UniqueConstraint(
            "company_id", "as_of_date", "method", name=op.f("uq_forecast_run_company_id")
        ),
    )
    op.create_table(
        "forecast_value",
        sa.Column("forecast_run_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=6), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period", sa.String(length=2), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("point", _NUMBER, nullable=False),
        sa.Column("p05", _NUMBER, nullable=True),
        sa.Column("p25", _NUMBER, nullable=True),
        sa.Column("p50", _NUMBER, nullable=True),
        sa.Column("p75", _NUMBER, nullable=True),
        sa.Column("p95", _NUMBER, nullable=True),
        sa.Column("source", sa.String(length=10), nullable=True),
        sa.CheckConstraint("kind IN ('line', 'driver')", name=op.f("ck_forecast_value_kind")),
        sa.ForeignKeyConstraint(
            ["forecast_run_id"],
            ["forecast_run.id"],
            name=op.f("fk_forecast_value_forecast_run_id_forecast_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "forecast_run_id",
            "kind",
            "code",
            "fiscal_year",
            "fiscal_period",
            name=op.f("pk_forecast_value"),
        ),
    )
    op.create_table(
        "valuation_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("forecast_run_id", sa.Integer(), nullable=False),
        sa.Column("method_code", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("inputs_json", sa.Text(), nullable=False),
        sa.Column("value_per_share", _NUMBER, nullable=True),
        sa.Column("equity_value", _NUMBER, nullable=True),
        sa.Column("enterprise_value", _NUMBER, nullable=True),
        sa.Column("upside", _NUMBER, nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["forecast_run_id"],
            ["forecast_run.id"],
            name=op.f("fk_valuation_run_forecast_run_id_forecast_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_valuation_run")),
        sa.UniqueConstraint(
            "forecast_run_id", "method_code", name=op.f("uq_valuation_run_forecast_run_id")
        ),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("entity", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(), nullable=True),
        sa.Column("field", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("rationale", sa.String(length=500), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_audit_log_company_id_company"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_company_id_id", "audit_log", ["company_id", "id"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("valuation_run")
    op.drop_table("forecast_value")
    op.drop_table("forecast_run")
    op.drop_table("forecast_snapshot")
    op.drop_index("ix_filing_company_id", table_name="filing")
