"""Facts -> canonical long frame. Pure."""

from collections.abc import Sequence

import pandas as pd

from bedrock.mapping.config import CanonicalItemDef

CANONICAL_COLUMNS = [
    "code",
    "period_start",
    "period_end",
    "value",
    "taxonomy",
    "concept",
    "unit",
    "accession_no",
    "form",
    "filed_at",
    "kind",
]

_OVERRIDE_BLOCK = 1_000_000  # every default ranks behind every override


def map_facts(
    latest: pd.DataFrame, mappings: pd.DataFrame, items: Sequence[CanonicalItemDef]
) -> pd.DataFrame:
    """For each (code, period_start, period_end) take the fact of the best-ranked concept:
    overrides first, then defaults, each by priority. Only facts in the item's unit count, and
    values are multiplied by the item's `sign`. A period one concept lacks falls back to the
    next, so a tag switch between years still yields a full series."""
    by_code = {i.code: i for i in items}
    ranked = mappings[mappings["canonical_code"].isin(list(by_code))].copy()
    ranked["rank"] = [
        priority + (0 if is_override else _OVERRIDE_BLOCK)
        for priority, is_override in zip(ranked["priority"], ranked["is_override"], strict=True)
    ]
    joined = latest.merge(
        ranked[["canonical_code", "taxonomy", "concept", "rank"]],
        on=["taxonomy", "concept"],
        how="inner",
    )
    joined["code"] = joined["canonical_code"]
    in_unit = pd.Series(
        [by_code[c].unit == u for c, u in zip(joined["code"], joined["unit"], strict=True)],
        index=joined.index,
        dtype=bool,
    )
    joined = joined[in_unit]
    best = joined.sort_values("rank", kind="stable").drop_duplicates(
        subset=["code", "period_start", "period_end"], keep="first"
    )
    out = best.sort_values(["code", "period_end"], kind="stable").reset_index(drop=True)
    out["value"] = [v * by_code[c].sign for v, c in zip(out["value"], out["code"], strict=True)]
    out["kind"] = [by_code[c].kind for c in out["code"]]
    return out[CANONICAL_COLUMNS]
