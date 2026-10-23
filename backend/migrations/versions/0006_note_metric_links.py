"""note metric links: note.metric_kind, note.metric_code

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("note") as batch:
        batch.add_column(sa.Column("metric_kind", sa.String(), nullable=True))
        batch.add_column(sa.Column("metric_code", sa.String(), nullable=True))
        batch.create_check_constraint(
            op.f("ck_note_metric_both_or_none"), "(metric_kind IS NULL) = (metric_code IS NULL)"
        )
        batch.create_check_constraint(
            op.f("ck_note_metric_kind"),
            "metric_kind IS NULL OR metric_kind IN ('ratio', 'capital', 'quality')",
        )
        batch.create_check_constraint(
            op.f("ck_note_line_or_metric"), "canonical_code IS NULL OR metric_kind IS NULL"
        )
        batch.create_index("ix_note_company_metric", ["company_id", "metric_kind", "metric_code"])


def downgrade() -> None:
    # Metric links are lost; the notes themselves stay (unlinked).
    with op.batch_alter_table("note") as batch:
        batch.drop_index("ix_note_company_metric")
        batch.drop_constraint(op.f("ck_note_line_or_metric"), type_="check")
        batch.drop_constraint(op.f("ck_note_metric_kind"), type_="check")
        batch.drop_constraint(op.f("ck_note_metric_both_or_none"), type_="check")
        batch.drop_column("metric_code")
        batch.drop_column("metric_kind")
