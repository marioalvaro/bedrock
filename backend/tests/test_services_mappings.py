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
