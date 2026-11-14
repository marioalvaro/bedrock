"""`sync_mappings` over a mapping directory: defaults, overrides and excludes."""

from pathlib import Path

from sqlalchemy.orm import Session

from bedrock.repositories import mappings as mappings_repo
from bedrock.services.mappings import sync_mappings

from .test_mapping_config import VALID
from .test_repositories import _company


def test_sync_applies_each_followed_companys_excludes(db_session: Session, tmp_path: Path) -> None:
    (tmp_path / "canonical_items.yaml").write_text(VALID)
    (tmp_path / "overrides").mkdir()
    (tmp_path / "overrides" / "AAPL.yaml").write_text(
        "gross_profit: {exclude: [GrossProfit]}\nrevenue: {concepts: [Custom]}\n"
    )
    aapl = _company(db_session)
    msft = _company(db_session, "MSFT", "0000789019")

    sync_mappings(db_session, tmp_path)
    db_session.commit()

    mine = mappings_repo.mappings_for(db_session, aapl.id)
    other = mappings_repo.mappings_for(db_session, msft.id)
    assert "GrossProfit" not in set(mine["concept"])
    assert "GrossProfit" in set(other["concept"])
    assert "Custom" in set(mine["concept"])
    assert "Custom" not in set(other["concept"])


def test_signed_members_keep_their_weight_through_the_database(
    db_session: Session, tmp_path: Path
) -> None:
    (tmp_path / "canonical_items.yaml").write_text(
        VALID.replace("[CostOfRevenue]", '["CostOfRevenue - Rebates + Freight", "-Credits"]')
    )
    (tmp_path / "overrides").mkdir()
    (tmp_path / "overrides" / "AAPL.yaml").write_text('revenue: ["-Refunds"]\n')
    aapl = _company(db_session)

    sync_mappings(db_session, tmp_path)
    db_session.commit()

    frame = mappings_repo.mappings_for(db_session, aapl.id)
    cost = frame[frame["canonical_code"] == "cost_of_revenue"]
    assert list(zip(cost["concept"], cost["priority"], cost["weight"], strict=True)) == [
        ("CostOfRevenue", 0, 1),
        ("Rebates", 0, -1),
        ("Freight", 0, 1),
        ("Credits", 1, -1),
    ]
    override = frame[frame["is_override"]]
    assert list(zip(override["concept"], override["weight"], strict=True)) == [("Refunds", -1)]
    assert set(frame[frame["canonical_code"] == "revenue"]["weight"]) == {1, -1}


def test_a_company_can_exclude_a_signed_default(db_session: Session, tmp_path: Path) -> None:
    (tmp_path / "canonical_items.yaml").write_text(
        VALID.replace("[CostOfRevenue]", '["CostOfRevenue - Rebates", CostOfRevenue]')
    )
    (tmp_path / "overrides").mkdir()
    (tmp_path / "overrides" / "AAPL.yaml").write_text(
        'cost_of_revenue: {exclude: ["CostOfRevenue - Rebates"]}\n'
    )
    aapl = _company(db_session)
    msft = _company(db_session, "MSFT", "0000789019")

    sync_mappings(db_session, tmp_path)
    db_session.commit()

    def cost(company_id: int) -> list[tuple[str, int, int]]:
        frame = mappings_repo.mappings_for(db_session, company_id)
        rows = frame[frame["canonical_code"] == "cost_of_revenue"]
        return list(zip(rows["concept"], rows["priority"], rows["weight"], strict=True))

    assert cost(aapl.id) == [("CostOfRevenue", 1, 1)]
    assert cost(msft.id) == [("CostOfRevenue", 0, 1), ("Rebates", 0, -1), ("CostOfRevenue", 1, 1)]
