"""Facts -> canonical long frame. Pure."""

from collections.abc import Hashable, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

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
_SUM_SEPARATOR = " + "


def map_facts(
    latest: pd.DataFrame, mappings: pd.DataFrame, items: Sequence[CanonicalItemDef]
) -> pd.DataFrame:
    """For each (code, period_start, period_end) take the fact of the best-ranked concept:
    overrides first, then defaults, each by priority. Only facts in the item's unit count, and
    values are multiplied by the item's `sign`. A period one concept lacks falls back to the
    next, so a tag switch between years still yields a full series.

    Mapping rows with the same (code, priority, is_override) form a summed concept, in frame order:
    the first row is the anchor. The group counts for a period only when the anchor has a fact
    (otherwise a partial group would beat a complete one ranked after it); the value is the sum of
    the members that have one, and the provenance `concept` joins their names with ` + `, while the
    taxonomy, filing and unit are the anchor's."""
    by_code = {i.code: i for i in items}
    ranked = mappings[mappings["canonical_code"].isin(list(by_code))].copy()
    ranked["rank"] = [
        priority + (0 if is_override else _OVERRIDE_BLOCK)
        for priority, is_override in zip(ranked["priority"], ranked["is_override"], strict=True)
    ]
    group = ranked.groupby(["canonical_code", "rank"])
    ranked["member"] = group.cumcount()
    ranked["group_size"] = group["rank"].transform("size")
    joined = latest.merge(
        ranked[["canonical_code", "taxonomy", "concept", "rank", "member", "group_size"]],
        on=["taxonomy", "concept"],
        how="inner",
    )
    joined["code"] = joined["canonical_code"]
    in_unit = pd.Series(
        [by_code[c].unit == u for c, u in zip(joined["code"], joined["unit"], strict=True)],
        index=joined.index,
        dtype=bool,
    )
    joined = _sum_groups(joined[in_unit])
    best = joined.sort_values("rank", kind="stable").drop_duplicates(
        subset=["code", "period_start", "period_end"], keep="first"
    )
    out = best.sort_values(["code", "period_end"], kind="stable").reset_index(drop=True)
    out["value"] = [v * by_code[c].sign for v, c in zip(out["value"], out["code"], strict=True)]
    out["kind"] = [by_code[c].kind for c in out["code"]]
    return out[CANONICAL_COLUMNS]


def _sum_groups(joined: pd.DataFrame) -> pd.DataFrame:
    """Collapse each summed group into one row per period (see `map_facts`); single concepts
    pass through."""
    grouped = joined["group_size"] > 1
    if not grouped.any():
        return joined
    members: dict[tuple[str, int, date | None, date], list[dict[Hashable, Any]]] = {}
    for record in joined[grouped].sort_values("member", kind="stable").to_dict("records"):
        start = None if pd.isna(record["period_start"]) else record["period_start"]
        key = (record["code"], record["rank"], start, record["period_end"])
        members.setdefault(key, []).append(record)
    summed: list[dict[Hashable, Any]] = []
    for rows in members.values():
        if rows[0]["member"] != 0:  # the anchor has no fact for this period
            continue
        total = sum((r["value"] for r in rows), Decimal(0))
        summed.append(
            {**rows[0], "value": total, "concept": _SUM_SEPARATOR.join(r["concept"] for r in rows)}
        )
    single = joined[~grouped]
    if not summed:
        return single
    return pd.concat([single, pd.DataFrame(summed, columns=joined.columns)], ignore_index=True)
