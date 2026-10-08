"""Latest and point-in-time views over all filing vintages of a fact. Pure."""

from datetime import date

import pandas as pd

NATURAL_KEY = ["taxonomy", "concept", "unit", "period_start", "period_end"]


def select_vintage(facts: pd.DataFrame, as_of: date | None = None) -> pd.DataFrame:
    """One fact per (taxonomy, concept, unit, period_start, period_end): the one from the
    filing with the max `filed_at` (ties: max `accession_no`). With `as_of`, only filings
    filed on or before that day are considered."""
    if as_of is not None:
        facts = facts[facts["filed_at"] <= as_of]
    ordered = facts.sort_values(["filed_at", "accession_no"], kind="stable")
    # drop_duplicates treats two NULL period_starts (instants) as equal, unlike SQL UNIQUE.
    return ordered.drop_duplicates(subset=NATURAL_KEY, keep="last").reset_index(drop=True)
