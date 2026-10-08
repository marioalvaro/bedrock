from pathlib import Path

from sqlalchemy.orm import Session

from bedrock.mapping.config import DEFAULT_ITEMS_PATH, load_canonical_items, load_overrides
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import mappings as mappings_repo

DEFAULT_MAPPING_DIR = DEFAULT_ITEMS_PATH.parent


def sync_mappings(session: Session, mapping_dir: Path = DEFAULT_MAPPING_DIR) -> None:
    """Make the stored canonical items and mappings equal the YAML in `mapping_dir`: the
    defaults, plus `overrides/<TICKER>.yaml` for each followed company (others are ignored).
    The caller commits."""
    items = load_canonical_items(mapping_dir / DEFAULT_ITEMS_PATH.name)
    overrides_dir = mapping_dir / "overrides"
    mappings_repo.replace_mappings(
        session,
        items,
        {
            company.id: load_overrides(overrides_dir, company.ticker, items)
            for company in companies_repo.list_all(session)
        },
    )
