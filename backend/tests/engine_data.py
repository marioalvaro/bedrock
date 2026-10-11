"""Synthetic fact frames for the pure engines: a fictional company, no network, no DB.

`FictCo` has a June fiscal year end. Its fiscal years run 1 Jul – 30 Jun, with quarters ending
30 Sep, 31 Dec and 31 Mar. Facts are built the way 10-Ks and 10-Qs report them.
"""

from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from bedrock.mapping.config import CanonicalItemDef

FACT_COLUMNS = [
    "taxonomy",
    "concept",
    "unit",
    "period_start",
    "period_end",
    "value",
    "accession_no",
    "form",
    "filed_at",
]
MAPPING_COLUMNS = ["canonical_code", "taxonomy", "concept", "priority", "is_override"]

Row = dict[str, object]


def fact(
    concept: str,
    start: date | None,
    end: date,
    value: int | str | Decimal,
    *,
    accession: str = "0001-24-000001",
    form: str = "10-K",
    filed: date | None = None,
    taxonomy: str = "us-gaap",
    unit: str = "USD",
) -> Row:
    return {
        "taxonomy": taxonomy,
        "concept": concept,
        "unit": unit,
        "period_start": start,
        "period_end": end,
        "value": Decimal(str(value)),
        "accession_no": accession,
        "form": form,
        "filed_at": filed or end + timedelta(days=45),
    }


def facts(rows: Iterable[Row]) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=FACT_COLUMNS).astype(
        {"period_start": "object", "period_end": "object", "value": "object", "filed_at": "object"}
    )


def mappings(*rows: tuple[str, str, int] | tuple[str, str, int, bool]) -> pd.DataFrame:
    """(code, "taxonomy:Concept" or bare concept, priority[, is_override])."""
    out = []
    for row in rows:
        code, concept, priority = row[:3]
        taxonomy, _, name = str(concept).rpartition(":")
        out.append(
            {
                "canonical_code": code,
                "taxonomy": taxonomy or "us-gaap",
                "concept": name,
                "priority": priority,
                "is_override": row[3] if len(row) == 4 else False,
            }
        )
    return pd.DataFrame(out, columns=MAPPING_COLUMNS)


def item(
    code: str,
    statement: str = "IS",
    *,
    kind: str = "flow",
    unit: str = "USD",
    sign: int = 1,
    parent: str | None = None,
    derive: str | None = None,
    residual: bool = False,
    concepts: Sequence[str] = (),
) -> CanonicalItemDef:
    return CanonicalItemDef(
        code=code,
        statement=statement,
        label=code.replace("_", " ").capitalize(),
        kind=kind,
        unit=unit,
        sign=sign,
        parent=parent,
        concepts=tuple(concepts),
        derive=derive,
        residual=residual,
    )


# --- Canonical frames (what `map_facts` returns) -------------------------------------------


def canon(
    code: str,
    start: date | None,
    end: date,
    value: int | str | Decimal = 1,
    *,
    kind: str = "flow",
    concept: str = "Concept",
    unit: str = "USD",
    accession: str = "0001-24-000001",
    form: str = "10-K",
    filed: date | None = None,
) -> Row:
    return {
        "code": code,
        "period_start": start,
        "period_end": end,
        "value": Decimal(str(value)),
        "taxonomy": "us-gaap",
        "concept": concept,
        "unit": unit,
        "accession_no": accession,
        "form": form,
        "filed_at": filed or end + timedelta(days=45),
        "kind": kind,
    }


def canon_frame(rows: Iterable[Row]) -> pd.DataFrame:
    from bedrock.mapping.mapper import CANONICAL_COLUMNS

    return pd.DataFrame(list(rows), columns=CANONICAL_COLUMNS).astype(
        {"period_start": "object", "period_end": "object", "value": "object", "filed_at": "object"}
    )


# --- FictCo: a June fiscal year end --------------------------------------------------------

Quarters = Sequence[int | None]  # discrete Q1..Q4


def fy_dates(fy: int) -> tuple[date, date, tuple[date, date, date]]:
    """FY2023 = 1 Jul 2022 .. 30 Jun 2023; quarters end 30 Sep, 31 Dec, 31 Mar."""
    return (
        date(fy - 1, 7, 1),
        date(fy, 6, 30),
        (date(fy - 1, 9, 30), date(fy - 1, 12, 31), date(fy, 3, 31)),
    )


def flow_facts(
    concept: str,
    quarters: dict[int, Quarters],
    *,
    ytd_only: bool = False,
    skip: frozenset[tuple[int, int]] = frozenset(),
    unit: str = "USD",
) -> list[Row]:
    """Facts as the 10-Ks and 10-Qs of a June-FY company report a flow.

    `quarters[fy]` holds the discrete Q1..Q4 values. Every 10-K reports the 12-month value; each
    10-Q reports the 3-month value (Q1 only 3 months) and the year-to-date value. With
    `ytd_only`, the 10-Qs report year-to-date values only. `skip` drops a (fy, quarter) 10-Q."""
    rows: list[Row] = []
    for fy, q in sorted(quarters.items()):
        start, end, q_ends = fy_dates(fy)
        total = sum(v or 0 for v in q)
        rows.append(
            fact(
                concept,
                start,
                end,
                total,
                accession=f"K-{fy}",
                unit=unit,
                filed=end + timedelta(days=60),
            )
        )
        running = 0
        previous_end = start - timedelta(days=1)
        for n, q_end in enumerate(q_ends, start=1):
            running += q[n - 1] or 0
            if (fy, n) in skip:
                previous_end = q_end
                continue
            common = {
                "accession": f"Q{n}-{fy}",
                "form": "10-Q",
                "filed": q_end + timedelta(days=40),
                "unit": unit,
            }
            if n == 1 or not ytd_only:
                rows.append(
                    fact(concept, previous_end + timedelta(days=1), q_end, q[n - 1] or 0, **common)
                )  # type: ignore[arg-type]
            if n > 1:
                rows.append(fact(concept, start, q_end, running, **common))  # type: ignore[arg-type]
            previous_end = q_end
    return rows


def instant_facts(concept: str, values: dict[int, Quarters], *, unit: str = "USD") -> list[Row]:
    """`values[fy]` = balances at Q1, Q2, Q3 and fiscal year end."""
    rows: list[Row] = []
    for fy, v in sorted(values.items()):
        _, end, q_ends = fy_dates(fy)
        for n, q_end in enumerate(q_ends, start=1):
            if v[n - 1] is not None:
                rows.append(
                    fact(
                        concept,
                        None,
                        q_end,
                        v[n - 1] or 0,
                        accession=f"Q{n}-{fy}",
                        form="10-Q",
                        filed=q_end + timedelta(days=40),
                        unit=unit,
                    )
                )
        if v[3] is not None:
            rows.append(
                fact(
                    concept,
                    None,
                    end,
                    v[3] or 0,
                    accession=f"K-{fy}",
                    unit=unit,
                    filed=end + timedelta(days=60),
                )
            )
    return rows
