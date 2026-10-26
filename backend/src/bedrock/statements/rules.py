"""The rule engine's per-sweep rules: accounting identities (R1) and the NCI zero rule (R1b). Pure.

Rules only ever fill empty cells (docs/erd/data.md "Rule engine"). Each function looks at the cells
as they stand and returns the cells to fill; `cells.py::solve_cells` owns the pass order and the
loop. Warnings go into a `WarningLog` that the caller owns, never into a global.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from bedrock.mapping.config import CanonicalItemDef, IdentityDef, SolveRule
from bedrock.statements.cell_types import (
    EMPTY,
    Cell,
    CellKey,
    Derivation,
    DerivationInput,
    FactRef,
    RuleWarning,
)
from bedrock.statements.periods import Period

# The tolerance of every accounting check (the balance check uses it too)
BALANCE_FLOOR = Decimal(1_000_000)
BALANCE_RELATIVE = Decimal("0.00001")

# A filing that tags any of these has non-controlling interests (R1b); the concepts mapped to the
# NCI lines are added from the company's mappings
NCI_INCLUSIVE_CONCEPTS = frozenset(
    {
        ("us-gaap", "ProfitLoss"),
        ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
        ("us-gaap", "MinorityInterest"),
        ("us-gaap", "NetIncomeLossAttributableToNoncontrollingInterest"),
    }
)
NCI_CODES = frozenset({"nci", "net_income_nci"})
# (the NCI line, the lines whose source names the filing that carries the statement), in order
NCI_LINES = (
    ("net_income_nci", ("net_income", "net_income_common")),
    ("nci", ("total_equity", "equity_parent")),
)


@dataclass(frozen=True)
class Rules:
    """What `solve_cells` applies beyond the mapped facts. `nci_filings` is the set of accession
    numbers whose filing tags an NCI concept; None switches R1b off (a frame that does not carry
    the filings' concepts cannot say that a filing tags none). `cover_shares` holds the cover-page
    share counts as a canonical-shaped frame (`code` `shares_outstanding`, `period_end` the end of
    the period the filing reports, split-adjusted); None switches the cover-page rule (R7) off."""

    identities: tuple[IdentityDef, ...] = ()
    nci_filings: frozenset[str] | None = None
    cover_shares: pd.DataFrame | None = None


NO_RULES = Rules()


def filings_tagging_nci(facts: pd.DataFrame, mappings: pd.DataFrame) -> frozenset[str]:
    """The accessions of `facts` (every vintage of the mapped concepts) that tag an NCI-inclusive
    total or an NCI concept, including the concepts the company's mappings give the NCI lines."""
    markers = set(NCI_INCLUSIVE_CONCEPTS)
    markers |= {
        (taxonomy, concept)
        for code, taxonomy, concept in zip(
            mappings["canonical_code"], mappings["taxonomy"], mappings["concept"], strict=True
        )
        if code in NCI_CODES
    }
    return frozenset(
        accession
        for accession, taxonomy, concept in zip(
            facts["accession_no"], facts["taxonomy"], facts["concept"], strict=True
        )
        if (taxonomy, concept) in markers
    )


class WarningLog:
    """Rule warnings in the order they arose, one per (rule, code, period)."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str, str], RuleWarning] = {}

    def add(self, warning: RuleWarning) -> None:
        self._by_key.setdefault((warning.rule, warning.code, warning.period_key), warning)

    def all(self) -> tuple[RuleWarning, ...]:
        return tuple(self._by_key.values())


@dataclass(frozen=True)
class _Candidate:
    identity: IdentityDef
    cell: Cell


def solve_identities(
    identities: Sequence[IdentityDef],
    by_code: Mapping[str, CanonicalItemDef],
    cells: Mapping[CellKey, Cell],
    periods: Sequence[Period],
    solved_nonzero: set[CellKey],
    log: WarningLog,
) -> list[tuple[CellKey, Cell]]:
    """One sweep over every identity and period, all read against the same `cells`: the cells to
    fill, at most one per cell. A flow or instant is solved in FY and Q1-Q3 only (Q4 follows).
    A value an identity solved that is not an inferred zero is added to `solved_nonzero`, and is
    never an operand of another identity."""
    found: dict[CellKey, list[_Candidate]] = {}
    for period in periods:
        if period.fiscal_period == "Q4":
            continue
        for identity in identities:
            solved = _solve(identity, by_code, cells, period, solved_nonzero, log)
            if solved is not None:
                found.setdefault((solved[0], period.key), []).append(
                    _Candidate(identity, solved[1])
                )

    out: list[tuple[CellKey, Cell]] = []
    for key, candidates in found.items():
        winner = candidates[0]
        for other in candidates[1:]:
            if other.cell.value != winner.cell.value:
                log.add(
                    RuleWarning(
                        other.identity.id,
                        key[0],
                        key[1],
                        other.cell.value,
                        f"gives {other.cell.value} where {winner.identity.id} gives "
                        f"{winner.cell.value}; kept {winner.identity.id}",
                    )
                )
        out.append((key, winner.cell))
        if winner.cell.provenance != "zero_inferred":
            solved_nonzero.add(key)
    return out


def _solve(
    identity: IdentityDef,
    by_code: Mapping[str, CanonicalItemDef],
    cells: Mapping[CellKey, Cell],
    period: Period,
    solved_nonzero: set[CellKey],
    log: WarningLog,
) -> tuple[str, Cell] | None:
    if any(code not in by_code for _, code in identity.terms):
        return None
    values = {code: cells.get((code, period.key), EMPTY) for _, code in identity.terms}
    empty = [code for _, code in identity.terms if values[code].value is None]
    if len(empty) != 1 or empty[0] not in identity.solve or by_code[empty[0]].residual:
        return None
    target = empty[0]
    operands = [(coef, code) for coef, code in identity.terms if code != target]
    if any((code, period.key) in solved_nonzero for _, code in operands):
        return None  # no chaining
    sources = [src for _, code in operands if (src := values[code].source) is not None]
    if _same_fact(sources) or _built_from_each_other(operands, target, values):
        return None  # circular: the identity would restate its own inputs
    accessions = sorted({s.accession_no for s in sources})
    if len(accessions) > 1:
        log.add(
            RuleWarning(
                identity.id,
                target,
                period.key,
                None,
                f"operands come from different filings ({', '.join(accessions)}); not solved",
            )
        )
        return None

    result = identity_result(
        identity, target, {code: values[code].value or Decimal(0) for _, code in operands}
    )
    largest = max(abs(values[code].value or Decimal(0)) for _, code in operands)
    rule = identity.solve[target]
    cell = _accept(identity, rule, target, result, largest, operands, values, period, log)
    return None if cell is None else (target, cell)


def _accept(
    identity: IdentityDef,
    rule: SolveRule,
    target: str,
    result: Decimal,
    largest: Decimal,
    operands: Sequence[tuple[int, str]],
    values: Mapping[str, Cell],
    period: Period,
    log: WarningLog,
) -> Cell | None:
    tolerance = max(BALANCE_FLOOR, BALANCE_RELATIVE * largest)
    provenance: str = "derived"
    stored = result
    reason: str | None = None
    if rule.mode == "zero_only":
        if abs(result) <= tolerance:
            stored, provenance = Decimal(0), "zero_inferred"
        else:
            reason = f"expected about 0, found {result}; beyond the tolerance {tolerance}"
    elif rule.mode == "bounded":
        assert rule.max_ratio is not None
        if abs(result) > rule.max_ratio * largest:
            reason = (
                f"{result} is more than {rule.max_ratio * 100:g}% of the largest other term "
                f"({largest}); beyond the tolerance of the rule"
            )
    if reason is not None:
        log.add(RuleWarning(identity.id, target, period.key, result, reason))
        return None
    derivation = identity_derivation(
        identity,
        target,
        {code: values[code].value or Decimal(0) for _, code in operands},
        period.fiscal_period,
    )
    return Cell(
        stored,
        provenance,  # type: ignore[arg-type]
        derivation=derivation,
        solved_by=identity.id,
    )


def identity_result(identity: IdentityDef, target: str, operands: Mapping[str, Decimal]) -> Decimal:
    """The value `target` must have for the identity to hold, given every other term."""
    own = _target_coefficient(identity, target)
    total = sum(
        (coef * operands[code] for coef, code in identity.terms if code != target), Decimal(0)
    )
    return -own * total


def identity_derivation(
    identity: IdentityDef, target: str, operands: Mapping[str, Decimal], fiscal_period: str
) -> Derivation:
    """`identity gp: cost_of_revenue = revenue - gross_profit` and the operands it used, the terms
    that are added first."""
    own = _target_coefficient(identity, target)
    ordered = sorted(
        ((coef, code) for coef, code in identity.terms if code != target),
        key=lambda term: -own * term[0] < 0,
    )
    inputs = tuple(DerivationInput(code, fiscal_period, operands[code]) for _, code in ordered)
    return Derivation(_formula(identity, target, ordered), inputs)


def _target_coefficient(identity: IdentityDef, target: str) -> int:
    return next(coef for coef, code in identity.terms if code == target)


def _formula(identity: IdentityDef, target: str, ordered: Sequence[tuple[int, str]]) -> str:
    """`identity gp: cost_of_revenue = revenue - gross_profit`: the target isolated on the left."""
    own = _target_coefficient(identity, target)
    text = ""
    for coef, code in ordered:
        sign = -own * coef  # target = -(own) * sum(coef * term)
        text += (f" {'+' if sign > 0 else '-'} " if text else ("-" if sign < 0 else "")) + code
    return f"identity {identity.id}: {target} = {text}"


def _same_fact(sources: Sequence[FactRef]) -> bool:
    return len(set(sources)) < len(sources)


def _built_from_each_other(
    operands: Sequence[tuple[int, str]], target: str, values: Mapping[str, Cell]
) -> bool:
    """An operand computed by a `derive` formula from the identity's other operands or its target
    adds nothing to them (a total_liabilities derived as L&E less equity makes temporary equity 0
    for any company)."""
    codes = {code for _, code in operands} | {target}
    for _, code in operands:
        cell = values[code]
        if cell.solved_by is None and cell.derivation is not None:
            if any(i.code in codes - {code} for i in cell.derivation.inputs):
                return True
    return False


def infer_nci_zeros(
    cells: Mapping[CellKey, Cell],
    by_code: Mapping[str, CanonicalItemDef],
    periods: Sequence[Period],
    nci_filings: frozenset[str],
) -> list[tuple[CellKey, Cell]]:
    """R1b: an empty NCI line is 0 when the filing that carries the statement for the period tags
    no NCI-inclusive total and no NCI concept. Q4 follows from FY and Q1-Q3 (flows) or the year
    end (instants), so it is not inferred here."""
    out: list[tuple[CellKey, Cell]] = []
    for target, carriers in NCI_LINES:
        if target not in by_code:
            continue
        for period in periods:
            if period.fiscal_period == "Q4":
                continue
            if cells.get((target, period.key), EMPTY).value is not None:
                continue
            source = next(
                (
                    cell.source
                    for code in carriers
                    if (cell := cells.get((code, period.key), EMPTY)).source is not None
                ),
                None,
            )
            if source is None or source.accession_no in nci_filings:
                continue
            out.append(
                (
                    (target, period.key),
                    Cell(
                        Decimal(0),
                        "zero_inferred",
                        derivation=Derivation(
                            "no NCI-inclusive total or NCI concept tagged in "
                            f"{source.form} {source.accession_no}",
                            (),
                        ),
                    ),
                )
            )
    return out
