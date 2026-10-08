"""Pure parser for SEC companyfacts JSON: no DB, no network."""

from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class FilingRecord:
    accession_no: str
    form: str
    filed_at: date
    fiscal_year: int | None
    fiscal_period: str | None
    period_end: date


@dataclass(frozen=True)
class FactRecord:
    accession_no: str
    taxonomy: str
    concept: str
    unit: str
    period_start: date | None
    period_end: date
    fiscal_year: int | None
    fiscal_period: str | None
    frame: str | None
    value: Decimal


@dataclass(frozen=True)
class ParsedFacts:
    filings: list[FilingRecord]
    facts: list[FactRecord]


def parse_companyfacts(doc: dict[str, Any]) -> ParsedFacts:
    """Every taxonomy and unit. Facts without an accession are skipped; the first of two
    facts with the same natural key wins (SQLite cannot enforce that for NULL starts)."""
    facts: list[FactRecord] = []
    seen: set[tuple[str, str, str, str, date | None, date]] = set()
    forms: dict[str, tuple[str, date]] = {}
    for taxonomy, concepts in doc.get("facts", {}).items():
        for concept, body in concepts.items():
            for unit, rows in body.get("units", {}).items():
                for row in rows:
                    accession = row.get("accn")
                    if not accession:
                        continue
                    fact = FactRecord(
                        accession_no=accession,
                        taxonomy=taxonomy,
                        concept=concept,
                        unit=unit,
                        period_start=_date(row.get("start")),
                        period_end=date.fromisoformat(row["end"]),
                        fiscal_year=row.get("fy"),
                        fiscal_period=row.get("fp"),
                        frame=row.get("frame"),
                        value=Decimal(str(row["val"])),
                    )
                    key = (accession, taxonomy, concept, unit, fact.period_start, fact.period_end)
                    if key in seen:
                        continue
                    seen.add(key)
                    facts.append(fact)
                    forms.setdefault(accession, (row["form"], date.fromisoformat(row["filed"])))
    return ParsedFacts(filings=_filings(facts, forms), facts=facts)


def _filings(facts: list[FactRecord], forms: dict[str, tuple[str, date]]) -> list[FilingRecord]:
    by_accession: dict[str, list[FactRecord]] = {}
    for fact in facts:
        by_accession.setdefault(fact.accession_no, []).append(fact)

    filings = []
    for accession, group in by_accession.items():
        # Comparatives are always earlier than the period, and the `dei` cover facts are dated
        # after it, so the latest non-`dei` end is the period the filing reports on.
        pool = [f for f in group if f.taxonomy != "dei"] or group
        form, filed_at = forms[accession]
        filings.append(
            FilingRecord(
                accession_no=accession,
                form=form,
                filed_at=filed_at,
                fiscal_year=_most_common(f.fiscal_year for f in pool),
                fiscal_period=_most_common(f.fiscal_period for f in pool),
                period_end=max(f.period_end for f in pool),
            )
        )
    return sorted(filings, key=lambda f: (f.filed_at, f.accession_no))


def _most_common[T](values: Any) -> T | None:
    counts = Counter(v for v in values if v is not None)
    return counts.most_common(1)[0][0] if counts else None


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None
