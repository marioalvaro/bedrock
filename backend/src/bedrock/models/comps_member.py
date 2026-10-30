from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bedrock.models.base import Base


class CompsMember(Base):
    """A followed company that is a peer in a comps set."""

    __tablename__ = "comps_member"
    __table_args__ = (UniqueConstraint("comps_set_id", "peer_company_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    comps_set_id: Mapped[int] = mapped_column(
        ForeignKey("comps_set.id", ondelete="CASCADE"), nullable=False
    )
    peer_company_id: Mapped[int] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True
    )
