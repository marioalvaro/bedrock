"""manual-only companies: company.cik nullable, company.source

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rebuild_without_cascades() -> None:
    """Rebuilding `company` drops the old table, and with foreign keys on SQLite then deletes the
    rows of every table that cascades from it. The pragma is a no-op once a statement has opened
    a transaction, so this runs before anything else in the migration."""
    op.execute("PRAGMA foreign_keys=OFF")


def upgrade() -> None:
    _rebuild_without_cascades()
    with op.batch_alter_table("company") as batch:
        batch.alter_column("cik", existing_type=sa.String(), nullable=True)
        batch.add_column(sa.Column("source", sa.String(), nullable=False, server_default="sec"))
        batch.create_check_constraint(op.f("ck_company_source"), "source IN ('sec', 'manual')")


def downgrade() -> None:
    _rebuild_without_cascades()
    manual = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM company WHERE source = 'manual'"))
        .scalar_one()
    )
    if manual:
        raise RuntimeError(
            f"{manual} manual company(ies) have no CIK: delete them before downgrading"
        )
    with op.batch_alter_table("company") as batch:
        batch.drop_constraint(op.f("ck_company_source"), type_="check")
        batch.drop_column("source")
        batch.alter_column("cik", existing_type=sa.String(), nullable=False)
