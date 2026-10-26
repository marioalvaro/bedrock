from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class CustomLine(Base):
    """A child line the user added in an import (FR-DATA-16): `parent_code` is a canonical leaf or
    another custom line. Its values are `imported_fact` rows under `code`."""

    __tablename__ = "custom_line"
    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint("statement IN ('IS', 'BS', 'CF')", name="statement"),
        CheckConstraint("kind IN ('flow', 'instant', 'average')", name="kind"),
        CheckConstraint("unit IN ('USD', 'USD/shares', 'shares')", name="unit"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False
    )
    # custom:<slug>
    code: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    statement: Mapped[str] = mapped_column(String, nullable=False)
    parent_code: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
    children_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
