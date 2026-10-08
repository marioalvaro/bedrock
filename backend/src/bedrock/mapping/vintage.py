"""Latest and point-in-time views over all filing vintages of a fact. Pure."""

from collections.abc import Collection, Sequence
from datetime import date

import pandas as pd

NATURAL_KEY = ["taxonomy", "concept", "unit", "period_start", "period_end"]

# A set of (taxonomy, concept) pairs, any one of which stands for one balance-sheet total.
Anchor = Collection[tuple[str, str]]

# The totals a filing must carry to count as a full balance sheet: any code of a group will do
# (liabilities follow from liabilities-and-equity less equity, equity from its parent part).
BALANCE_TOTALS = (
    ("total_assets",),
    ("total_liabilities", "total_liabilities_and_equity"),
    ("total_equity", "equity_parent"),
)


def balance_snapshot(mappings: pd.DataFrame) -> list[set[tuple[str, str]]]:
    """The `snapshot` argument of `select_vintage` for a company: one anchor per balance-sheet
    total, made of every concept mapped to it, overrides included. Empty (the rule is off) when
    a total has no mapped concept, as nothing then tells a full balance sheet from a part."""
    anchors = [
        {
            (taxonomy, concept)
            for code, taxonomy, concept in zip(
                mappings["canonical_code"], mappings["taxonomy"], mappings["concept"], strict=True
            )
            if code in codes
        }
        for codes in BALANCE_TOTALS
    ]
    return anchors if all(anchors) else []


def select_vintage(
    facts: pd.DataFrame, as_of: date | None = None, snapshot: Sequence[Anchor] = ()
) -> pd.DataFrame:
    """One fact per (taxonomy, concept, unit, period_start, period_end): the one from the
    filing with the max `filed_at` (ties: max `accession_no`). With `as_of`, only filings
    filed on or before that day are considered.

    `snapshot` lists the balance-sheet totals (one anchor per total: assets, liabilities,
    equity). A later filing may restate one total and not the others, so with `snapshot` the
    instants of a balance date follow the latest filing that carries all the totals for it: the
    totals come from that filing alone, its other values win over later partial filings, and an
    item it does not carry (a footnote line, say) keeps its latest value. A date no filing covers
    completely keeps the latest value of each fact."""
    if as_of is not None:
        facts = facts[facts["filed_at"] <= as_of]
    ordered = facts.sort_values(["filed_at", "accession_no"], kind="stable")
    # drop_duplicates treats two NULL period_starts (instants) as equal, unlike SQL UNIQUE.
    latest = ordered.drop_duplicates(subset=NATURAL_KEY, keep="last").reset_index(drop=True)
    if not snapshot or latest.empty:
        return latest
    return _with_snapshots(ordered, latest, snapshot)


def _with_snapshots(
    ordered: pd.DataFrame, latest: pd.DataFrame, snapshot: Sequence[Anchor]
) -> pd.DataFrame:
    instants = ordered[ordered["period_start"].isna()]
    concepts: dict[tuple[date, str], set[tuple[str, str]]] = {}
    for end, accession, taxonomy, concept in zip(
        instants["period_end"],
        instants["accession_no"],
        instants["taxonomy"],
        instants["concept"],
        strict=True,
    ):
        concepts.setdefault((end, accession), set()).add((taxonomy, concept))
    complete = {key for key, present in concepts.items() if all(present & set(a) for a in snapshot)}
    if not complete:
        return latest

    # `ordered` is sorted by (filed_at, accession), so the last complete filing of a date wins.
    chosen: dict[date, str] = {}
    for end, accession in zip(instants["period_end"], instants["accession_no"], strict=True):
        if (end, accession) in complete:
            chosen[end] = accession

    totals = {pair for anchor in snapshot for pair in anchor}
    is_instant = latest["period_start"].isna()
    covered = latest["period_end"].isin(list(chosen))
    is_total = pd.Series(
        [(t, c) in totals for t, c in zip(latest["taxonomy"], latest["concept"], strict=True)],
        index=latest.index,
        dtype=bool,
    )
    from_snapshot = instants[
        [
            chosen.get(end) == accession
            for end, accession in zip(instants["period_end"], instants["accession_no"], strict=True)
        ]
    ]
    # The snapshot filing's rows go last, so they win over a later filing's row of the same fact.
    kept = latest[~(is_instant & covered & is_total)]
    merged = pd.concat([kept, from_snapshot], ignore_index=True)
    merged = merged.drop_duplicates(subset=NATURAL_KEY, keep="last")
    return merged.sort_values(["filed_at", "accession_no"], kind="stable").reset_index(drop=True)
