from collections.abc import Collection

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from bedrock.models.company import Company
from bedrock.models.comps_member import CompsMember
from bedrock.models.comps_set import CompsSet


def list_sets(session: Session, company_id: int) -> list[CompsSet]:
    """The company's sets by name."""
    stmt = select(CompsSet).where(CompsSet.company_id == company_id).order_by(CompsSet.name)
    return list(session.execute(stmt).scalars())


def get_set(session: Session, company_id: int, set_id: int) -> CompsSet | None:
    """The set, only when it belongs to the company."""
    stmt = select(CompsSet).where(CompsSet.company_id == company_id, CompsSet.id == set_id)
    return session.execute(stmt).scalar_one_or_none()


def members(session: Session, set_ids: Collection[int]) -> dict[int, list[Company]]:
    """The peer companies of each given set by ticker, in one query (a set without members has
    an empty list)."""
    found: dict[int, list[Company]] = {i: [] for i in set_ids}
    if not set_ids:
        return found
    stmt = (
        select(CompsMember.comps_set_id, Company)
        .join(Company, Company.id == CompsMember.peer_company_id)
        .where(CompsMember.comps_set_id.in_(set_ids))
        .order_by(CompsMember.comps_set_id, Company.ticker)
    )
    for set_id, peer in session.execute(stmt):
        found[set_id].append(peer)
    return found


def add_set(session: Session, comps_set: CompsSet, peer_ids: Collection[int]) -> CompsSet:
    """Adds the set with its members and flushes (no commit)."""
    session.add(comps_set)
    session.flush()
    replace_members(session, comps_set, peer_ids)
    return comps_set


def replace_members(session: Session, comps_set: CompsSet, peer_ids: Collection[int]) -> None:
    """Makes `peer_ids` the set's members and flushes (no commit)."""
    session.execute(delete(CompsMember).where(CompsMember.comps_set_id == comps_set.id))
    session.add_all(CompsMember(comps_set_id=comps_set.id, peer_company_id=i) for i in peer_ids)
    session.flush()


def delete_set(session: Session, comps_set: CompsSet) -> None:
    """Deletes the set and its members, and flushes (no commit)."""
    session.execute(delete(CompsMember).where(CompsMember.comps_set_id == comps_set.id))
    session.delete(comps_set)
    session.flush()
