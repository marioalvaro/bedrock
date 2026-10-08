from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class ConceptMapping(Base):
    """XBRL concept -> canonical item. `company_id` NULL is a default, else an override."""

    __tablename__ = "concept_mapping"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_code: Mapped[str] = mapped_column(ForeignKey("canonical_item.code"), nullable=False)
    taxonomy: Mapped[str] = mapped_column(String, nullable=False)
    concept: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)  # 0 is tried first
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=True
    )
