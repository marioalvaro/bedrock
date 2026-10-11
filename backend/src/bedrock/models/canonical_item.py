from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class CanonicalItem(Base):
    """A canonical line item, seeded from `canonical_items.yaml`."""

    __tablename__ = "canonical_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    statement: Mapped[str] = mapped_column(String, nullable=False)  # IS | BS | CF
    label: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # flow | instant | average
    unit: Mapped[str] = mapped_column(String, nullable=False)  # USD | USD/shares | shares
    sign: Mapped[int] = mapped_column(Integer, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_code: Mapped[str | None] = mapped_column(String, nullable=True)
