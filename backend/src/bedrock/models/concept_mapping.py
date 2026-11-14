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
    # M7b S3: +1, or -1 for a subtracted member of a summed concept (`A - B`)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    # M7b S4: a combined entry's covered codes joined with `,` ("" covers no row); null if plain
    covers: Mapped[str | None] = mapped_column(String, nullable=True)
