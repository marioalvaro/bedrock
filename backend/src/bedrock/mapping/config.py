"""Loading and validating the canonical item list and the per-company overrides.

Pure apart from reading the YAML files it is given.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

DEFAULT_ITEMS_PATH = Path(__file__).parent / "canonical_items.yaml"
DEFAULT_OVERRIDES_DIR = Path(__file__).parent / "overrides"

STATEMENTS = ("IS", "BS", "CF")
KINDS = ("flow", "instant", "average")
UNITS = ("USD", "USD/shares", "shares")
DEFAULT_TAXONOMY = "us-gaap"

_CODE = r"[a-z][a-z0-9_]*"
_FORMULA = re.compile(rf"^\s*({_CODE})(\s*[+-]\s*{_CODE})*\s*$")
_TERM = re.compile(rf"([+-]?)\s*({_CODE})")
# a member name holds no whitespace or sign of its own
_BAD_NAME = re.compile(r"\s|^[+-]|[+-]$")


class MappingConfigError(ValueError):
    """The mapping configuration is invalid; `code` is the offending canonical code."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(f"{code}: {message}" if code else message)
        self.code = code


@dataclass(frozen=True)
class CanonicalItemDef:
    code: str
    statement: str
    label: str
    kind: str
    unit: str
    sign: int
    parent: str | None
    concepts: tuple[str, ...]  # "taxonomy:Concept", in priority order
    derive: str | None
    residual: bool
    # M2: where a normalization adjustment of this line propagates, as (code, sign)
    rolls_into: tuple[tuple[str, int], ...] = ()
    # M3 S10c: a child line the user added in an import (`code` is `custom:<slug>`, `parent` a
    # canonical leaf or another custom line); it has no concept, formula or adjustment
    custom: bool = False
    # M7b S2: a line an accounting standard introduced (ASC 842 leases); its cells before the
    # company's first value are `not_applicable` in coverage, not gaps
    starts_with_standard: bool = False
    # M7b S4: the combined entries of `concepts` (docs/erd/data-coverage.md "Combined lines"), each
    # as (entry, the canonical codes whose amount is inside it); empty when there are none
    covers: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # M7b S5: the residual a new row is added back into for the forecast (docs/erd/data-coverage.md
    # "New canonical rows"), so the forecast keeps reading the residual it read before the row
    forecast_fold: str | None = None
    # M7b S5 (user, 2026-11-14): a line every company has. Coverage counts its empty cells as gaps
    # even when the company never reports it; another line with no value in any period is
    # `not_applicable` (statements/coverage.py)
    required: bool = False


# Memo lines, never adjusted: a charge that sits inside another line (adjust that line instead), and
# M7b S5's supplemental cash disclosures, which no statement total holds.
MEMO_CODES = frozenset({"goodwill_impairment", "cash_taxes_paid", "cash_interest_paid"})

# Lines that only feed an identity (R7): a company that does not report them has left nothing out,
# so Data gaps does not list them.
SUPPORT_CODES = frozenset(
    {
        "shares_issued",
        "treasury_shares",
        # M7b S4: the scope totals of docs/erd/data-coverage.md "Scope identities"
        "long_term_debt_total",
        "long_term_debt_current",
        "operating_lease_liabilities_total",
        "operating_lease_liabilities_current",
    }
)

SOLVE_MODES = ("zero_only", "exact", "bounded")


@dataclass(frozen=True)
class SolveRule:
    """How an identity may fill one of its terms (docs/erd/data.md "R1: identities")."""

    mode: str  # zero_only | exact | bounded
    max_ratio: Decimal | None  # bounded: the largest |result| / largest |other term|


@dataclass(frozen=True)
class IdentityDef:
    """An accounting identity over canonical items of one statement, in displayed values.
    `terms` has the equation moved to one side: sum(coefficient * value) = 0, coefficients ±1."""

    id: str
    equation: str
    terms: tuple[tuple[int, str], ...]
    solve: Mapping[str, SolveRule]
    note: str = ""  # M7b S4: said after the formula of a solved cell (its scope), else empty


def split_concept(text: str) -> tuple[str, str]:
    """`Revenues` -> (`us-gaap`, `Revenues`); `ifrs-full:Revenue` -> (`ifrs-full`, `Revenue`)."""
    taxonomy, sep, concept = text.partition(":")
    return (taxonomy, concept) if sep else (DEFAULT_TAXONOMY, text)


# A member is added after `+` (spaces optional) and subtracted after ` - ` (a space on both
# sides, since a taxonomy prefix such as `ifrs-full` holds a hyphen); a leading `-` negates the
# anchor.
_MEMBER_SEPARATOR = re.compile(r"\s*(\+)\s*|\s+(-)\s+")
_LEADING_MINUS = re.compile(r"^\s*-\s*")


def signed_members(entry: str) -> list[tuple[int, str, str]]:
    """A concept entry `A + B - C` -> [(1, taxonomy, A), (1, taxonomy, B), (-1, taxonomy, C)]:
    the weighted members of a summed concept, anchor first. A plain concept is a group of one,
    `-A` a group of one subtracted member. Members are not validated here (see `_qualify_entry`)."""
    anchor_weight = 1
    rest = entry
    if (lead := _LEADING_MINUS.match(entry)) is not None:
        anchor_weight, rest = -1, entry[lead.end() :]
    parts = _MEMBER_SEPARATOR.split(rest)
    # split() returns [member, plus, minus, member, plus, minus, member, ...]
    members = [(anchor_weight, parts[0])]
    for at in range(1, len(parts), 3):
        weight = -1 if parts[at + 1] == "-" else 1
        members.append((weight, parts[at + 2]))
    return [(weight, *split_concept(member.strip())) for weight, member in members]


def covers_text(item: CanonicalItemDef, entry: str) -> str | None:
    """How `concept_mapping.covers` stores an entry of `item`: None for a plain entry, else its
    covered codes joined with `,` (an empty string for a combined entry that covers no row)."""
    return next((",".join(codes) for e, codes in item.covers if e == entry), None)


def covered_codes(text: str | None) -> tuple[str, ...] | None:
    """`covers_text` read back: None for a plain entry, else the covered codes."""
    return None if text is None else tuple(c for c in text.split(",") if c)


def split_group(entry: str) -> list[tuple[str, str]]:
    """A concept entry `A + B` -> [(taxonomy, A), (taxonomy, B)]: the members of a summed concept,
    anchor first, without their weights (`signed_members`). A plain concept is a group of one."""
    return [(taxonomy, concept) for _, taxonomy, concept in signed_members(entry)]


def parse_formula(text: str) -> list[tuple[int, str]]:
    """`a - b + c` -> [(1, "a"), (-1, "b"), (1, "c")]."""
    if not _FORMULA.match(text):
        raise MappingConfigError(f"malformed formula {text!r}")
    return [(-1 if sign == "-" else 1, code) for sign, code in _TERM.findall(text)]


def _read_items_file(path: Path) -> tuple[Any, Any]:
    """The raw `(items, identities)` of the file: a plain list of items, or a mapping with an
    `items` list and an optional `identities` list."""
    raw = yaml.safe_load(path.read_text())
    if isinstance(raw, dict):
        if set(raw) - {"items", "identities"}:
            raise MappingConfigError(f"{path.name} takes only `items` and `identities`")
        return raw.get("items"), raw.get("identities")
    return raw, None


def load_canonical_items(path: Path = DEFAULT_ITEMS_PATH) -> list[CanonicalItemDef]:
    raw, _ = _read_items_file(path)
    if not isinstance(raw, list):
        raise MappingConfigError(f"{path.name} must be a list of items")
    items = [_item(entry) for entry in raw]
    _validate(items)
    return items


def load_identities(path: Path, items: Sequence[CanonicalItemDef]) -> list[IdentityDef]:
    """The file's `identities:` list, validated against `items`; none for a plain item list."""
    _, raw = _read_items_file(path)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise MappingConfigError(f"`identities` in {path.name} must be a list")
    by_code = {i.code: i for i in items}
    identities = [_identity(entry, by_code) for entry in raw]
    ids = [i.id for i in identities]
    for identity_id in ids:
        if ids.count(identity_id) > 1:
            raise MappingConfigError(f"duplicate identity id {identity_id!r}")
    return identities


def load_overrides(
    directory: Path, ticker: str, items: Sequence[CanonicalItemDef] | None = None
) -> dict[str, list[str]]:
    """The concepts a company adds ahead of the defaults. `<ticker>.yaml` maps `code` to either a
    list of concepts or `{concepts: [...], exclude: ...}` (see `load_excludes`). Concepts come
    back as `taxonomy:Concept`; a code that only excludes has no entry."""
    parsed = _read_overrides(directory, ticker, items)
    return {code: added for code, (added, _) in parsed.items() if added}


def load_excludes(
    directory: Path, ticker: str, items: Sequence[CanonicalItemDef]
) -> dict[str, list[str]]:
    """The default concepts a company switches off, by code, each as `taxonomy:Concept` (or the
    summed entry `taxonomy:A + taxonomy:B`) exactly as in the item's defaults. `exclude: [...]`
    names defaults; `exclude: all` drops every default of the item, so it falls back to its
    `derive` formula, else stays empty. An exclude that names no default of the item is an error,
    so stale excludes fail."""
    parsed = _read_overrides(directory, ticker, items)
    return {code: dropped for code, (_, dropped) in parsed.items() if dropped}


def _read_overrides(
    directory: Path, ticker: str, items: Sequence[CanonicalItemDef] | None
) -> dict[str, tuple[list[str], list[str]]]:
    path = directory / f"{ticker.upper()}.yaml"
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise MappingConfigError(f"{path.name} must map codes to concept lists")
    by_code = {i.code: i for i in items} if items is not None else None
    parsed: dict[str, tuple[list[str], list[str]]] = {}
    for code, entry in raw.items():
        item = None
        if by_code is not None:
            if code not in by_code:
                raise MappingConfigError(f"override for unknown code in {path.name}", code)
            item = by_code[code]
            if item.residual:
                raise MappingConfigError("residual items cannot be overridden", code)
        concepts, exclude = _override_entry(path.name, code, entry)
        added = _qualify(code, concepts)
        dropped: list[str] = []
        if exclude is not None:
            if item is None:
                raise MappingConfigError("excludes need the canonical items to check", code)
            dropped = _excluded(code, exclude, item)
            if set(dropped) & set(added):
                raise MappingConfigError("a concept cannot be both added and excluded", code)
        parsed[code] = (added, dropped)
    return parsed


def _override_entry(file: str, code: str, entry: Any) -> tuple[list[str], list[str] | str | None]:
    if isinstance(entry, list):
        concepts, exclude = entry, None
    elif isinstance(entry, dict):
        if not entry or set(entry) - {"concepts", "exclude"}:
            raise MappingConfigError(
                f"an override mapping takes `concepts` and `exclude` in {file}", code
            )
        concepts, exclude = entry.get("concepts", []), entry.get("exclude")
        if "exclude" in entry and not (
            exclude == "all"
            or (isinstance(exclude, list) and exclude and all(isinstance(e, str) for e in exclude))
        ):
            raise MappingConfigError(f"exclude must be `all` or a list of concepts in {file}", code)
    else:
        raise MappingConfigError(f"override must be a list of concepts in {file}", code)
    if isinstance(concepts, list) and any(isinstance(c, dict) for c in concepts):
        raise MappingConfigError(
            f"a combined entry is a default, never an override, in {file}", code
        )
    if not isinstance(concepts, list) or not all(isinstance(c, str) for c in concepts):
        raise MappingConfigError(f"override must be a list of concepts in {file}", code)
    return concepts, exclude


def _excluded(code: str, exclude: list[str] | str, item: CanonicalItemDef) -> list[str]:
    if exclude == "all":
        if not item.concepts:
            raise MappingConfigError("exclude: all but the item has no default concept", code)
        return list(item.concepts)
    assert isinstance(exclude, list)
    dropped = _qualify(code, exclude)
    for entry in dropped:
        if entry not in item.concepts:
            raise MappingConfigError(f"{entry!r} is not a default concept, cannot exclude", code)
    return dropped


def formula_order(items: Sequence[CanonicalItemDef]) -> list[CanonicalItemDef]:
    """Items with a `derive` formula, operands before the items that use them."""
    by_code = {i.code: i for i in items}
    ordered: list[CanonicalItemDef] = []
    done: set[str] = set()
    visiting: set[str] = set()

    def visit(code: str) -> None:
        item = by_code.get(code)
        if item is None or item.derive is None or code in done:
            return
        if code in visiting:
            raise MappingConfigError("formula cycle", code)
        visiting.add(code)
        for _, operand in parse_formula(item.derive):
            visit(operand)
        visiting.discard(code)
        done.add(code)
        ordered.append(item)

    for item in items:
        visit(item.code)
    return ordered


def is_adjustable(item: CanonicalItemDef) -> bool:
    """A normalization adjustment may target USD flows and instants (residual lines included), not
    the computed-only lines (`derive` and no concepts, not residual), memo lines, EPS, shares or
    per-share figures."""
    computed_only = item.derive is not None and not item.concepts and not item.residual
    return (
        not item.custom
        and item.unit == "USD"
        and item.kind in ("flow", "instant")
        and not computed_only
        and item.code not in MEMO_CODES
    )


def _edges(item: CanonicalItemDef) -> tuple[tuple[str, int], ...]:
    """The lines a delta of `item` flows into directly: its `rolls_into`, else (balance sheet and
    cash flow, whose parents are sums of their children) its `parent`."""
    if item.rolls_into:
        return item.rolls_into
    if item.statement != "IS" and item.parent is not None:
        return ((item.parent, 1),)
    return ()


def propagation_targets(items: Sequence[CanonicalItemDef], code: str) -> dict[str, int]:
    """Every line a delta of `code` reaches, transitively, with the signs multiplied along the
    path (paths to one target add up)."""
    by_code = {i.code: i for i in items}
    targets: dict[str, int] = {}

    def walk(current: str, sign: int) -> None:
        for target, edge_sign in _edges(by_code[current]):
            targets[target] = targets.get(target, 0) + sign * edge_sign
            walk(target, sign * edge_sign)

    walk(code, 1)
    return {c: s for c, s in targets.items() if s != 0}


def _rolls_into(code: str, raw: Any) -> tuple[tuple[str, int], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(t, str) for t in raw):
        raise MappingConfigError("rolls_into must be a list of codes", code)
    targets = []
    for text in raw:
        sign = -1 if text.startswith("-") else 1
        target = text[1:] if text.startswith("-") else text
        if not re.fullmatch(_CODE, target):
            raise MappingConfigError(f"malformed rolls_into entry {text!r}", code)
        targets.append((target, sign))
    if len({t for t, _ in targets}) != len(targets):
        raise MappingConfigError("duplicate rolls_into target", code)
    return tuple(targets)


def _item(entry: Any) -> CanonicalItemDef:
    if not isinstance(entry, dict) or not isinstance(entry.get("code"), str):
        raise MappingConfigError(f"item without a code: {entry!r}")
    code = entry["code"]
    for field in ("statement", "label", "kind", "unit", "sign"):
        if field not in entry:
            raise MappingConfigError(f"missing field {field!r}", code)
    for field, allowed in (("statement", STATEMENTS), ("kind", KINDS), ("unit", UNITS)):
        if entry[field] not in allowed:
            raise MappingConfigError(
                f"{field} must be one of {allowed}, got {entry[field]!r}", code
            )
    if entry["sign"] not in (1, -1) or isinstance(entry["sign"], bool):
        raise MappingConfigError(f"sign must be 1 or -1, got {entry['sign']!r}", code)
    concepts, covers = _concept_entries(code, entry.get("concepts") or [])
    starts_with_standard = entry.get("starts_with_standard", False)
    if not isinstance(starts_with_standard, bool):
        raise MappingConfigError(
            f"starts_with_standard must be true or false, got {starts_with_standard!r}", code
        )
    if starts_with_standard and (entry.get("residual") or entry.get("derive") is not None):
        raise MappingConfigError(
            "starts_with_standard is for a reported line, not a residual or a computed one", code
        )
    forecast_fold = _forecast_fold(code, entry)
    required = entry.get("required", False)
    if not isinstance(required, bool):
        raise MappingConfigError(f"required must be true or false, got {required!r}", code)
    if required and entry.get("residual"):
        raise MappingConfigError("required is for a line coverage counts, not a residual", code)
    return CanonicalItemDef(
        code=code,
        statement=entry["statement"],
        label=str(entry["label"]),
        kind=entry["kind"],
        unit=entry["unit"],
        sign=entry["sign"],
        parent=entry.get("parent"),
        concepts=tuple(_qualify(code, concepts)),
        derive=entry.get("derive"),
        covers=covers,
        residual=bool(entry.get("residual", False)),
        rolls_into=_rolls_into(code, entry.get("rolls_into")),
        starts_with_standard=starts_with_standard,
        forecast_fold=forecast_fold,
        required=required,
    )


def _forecast_fold(code: str, entry: dict[str, Any]) -> str | None:
    """The item's `forecast_fold`: a code, on a reported line (no `derive`) with a parent; the
    target is checked against the other items in `_validate`."""
    target = entry.get("forecast_fold")
    if target is None:
        return None
    if not isinstance(target, str) or not re.fullmatch(_CODE, target):
        raise MappingConfigError(f"forecast_fold must be a code, got {target!r}", code)
    if entry.get("residual") or entry.get("derive") is not None:
        raise MappingConfigError("forecast_fold is for a reported line, not a computed one", code)
    if entry.get("parent") is None:
        raise MappingConfigError(
            "forecast_fold needs a row with a parent (a memo row has none)", code
        )
    return target


def _concept_entries(
    code: str, raw: Any
) -> tuple[list[str], tuple[tuple[str, tuple[str, ...]], ...]]:
    """The item's concept entries as text, and its combined entries (`{concept, covers}`) as
    (qualified entry, covered codes). A combined entry is a single concept and comes after every
    plain entry; the covered codes are checked against the other items in `_validate`."""
    if not isinstance(raw, list):
        raise MappingConfigError("concepts must be a list of strings", code)
    concepts: list[str] = []
    covers: list[tuple[str, tuple[str, ...]]] = []
    for entry in raw:
        if isinstance(entry, str):
            if covers:
                raise MappingConfigError(
                    "a combined entry comes after every plain entry of the item", code
                )
            concepts.append(entry)
            continue
        if not isinstance(entry, dict) or not isinstance(entry.get("concept"), str):
            raise MappingConfigError(
                "concepts must be a list of strings or {concept, covers}", code
            )
        if set(entry) != {"concept", "covers"}:
            raise MappingConfigError("a combined entry takes exactly `concept` and `covers`", code)
        codes = entry["covers"]
        if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
            raise MappingConfigError("covers must be a list of codes", code)
        if len(set(codes)) != len(codes):
            raise MappingConfigError("a combined entry covers a code twice", code)
        if len(signed_members(entry["concept"])) != 1 or entry["concept"].strip().startswith("-"):
            raise MappingConfigError("a combined entry is a single concept, not a sum", code)
        concepts.append(entry["concept"])
        covers.append((_qualify_entry(code, entry["concept"]), tuple(codes)))
    return concepts, tuple(covers)


def _identity(entry: Any, by_code: dict[str, CanonicalItemDef]) -> IdentityDef:
    if not isinstance(entry, dict):
        raise MappingConfigError(f"identity must be a mapping, got {entry!r}")
    for field in ("id", "equation", "solve"):
        if field not in entry:
            raise MappingConfigError(f"identity is missing field {field!r}: {entry!r}")
    identity_id, equation = entry["id"], entry["equation"]
    if not isinstance(identity_id, str) or not identity_id or not isinstance(equation, str):
        raise MappingConfigError(f"identity needs a text `id` and `equation`: {entry!r}")
    if set(entry) - {"id", "equation", "solve", "note"}:
        raise MappingConfigError(f"{identity_id}: unknown identity field in {entry!r}")
    note = entry.get("note", "")
    if not isinstance(note, str):
        raise MappingConfigError(f"{identity_id}: the note must be text")
    terms = _equation_terms(identity_id, equation)
    for _, code in terms:
        if code not in by_code:
            raise MappingConfigError(f"{identity_id}: unknown code {code!r}", code)
        if by_code[code].statement != by_code[terms[0][1]].statement:
            raise MappingConfigError(f"{identity_id}: {code!r} is on another statement", code)
    if len({code for _, code in terms}) != len(terms):
        raise MappingConfigError(f"{identity_id}: repeated term in {equation!r}")
    return IdentityDef(
        identity_id,
        equation.strip(),
        terms,
        _solve_rules(identity_id, entry["solve"], terms, by_code),
        note.strip(),
    )


def _equation_terms(identity_id: str, equation: str) -> tuple[tuple[int, str], ...]:
    sides = equation.split("=")
    if len(sides) != 2:
        raise MappingConfigError(f"{identity_id}: malformed equation {equation!r}")
    try:
        left, right = (parse_formula(side) for side in sides)
    except MappingConfigError as error:
        raise MappingConfigError(f"{identity_id}: malformed equation {equation!r}") from error
    return tuple([*left, *((-sign, code) for sign, code in right)])


def _solve_rules(
    identity_id: str,
    raw: Any,
    terms: tuple[tuple[int, str], ...],
    by_code: dict[str, CanonicalItemDef],
) -> dict[str, SolveRule]:
    if not isinstance(raw, dict) or not raw:
        raise MappingConfigError(f"{identity_id}: solve must name at least one term")
    rules: dict[str, SolveRule] = {}
    for code, spec in raw.items():
        if code not in {c for _, c in terms}:
            raise MappingConfigError(f"{identity_id}: solve key {code!r} is not a term", code)
        if by_code[code].residual:
            raise MappingConfigError(f"{identity_id}: {code!r} is a residual, never solved", code)
        if not isinstance(spec, dict) or "mode" not in spec:
            raise MappingConfigError(f"{identity_id}: solve for {code!r} needs a mode", code)
        if set(spec) - {"mode", "max_ratio"}:
            raise MappingConfigError(f"{identity_id}: unknown key in solve for {code!r}", code)
        if spec["mode"] not in SOLVE_MODES:
            raise MappingConfigError(f"{identity_id}: unknown mode {spec['mode']!r}", code)
        rules[code] = SolveRule(spec["mode"], _max_ratio(identity_id, code, spec))
    return rules


def _max_ratio(identity_id: str, code: str, spec: dict[str, Any]) -> Decimal | None:
    if spec["mode"] != "bounded":
        return None
    try:
        ratio = Decimal(str(spec["max_ratio"]))
    except (KeyError, InvalidOperation):
        raise MappingConfigError(
            f"{identity_id}: bounded needs a positive max_ratio for {code!r}", code
        ) from None
    if not ratio.is_finite() or ratio <= 0:
        raise MappingConfigError(
            f"{identity_id}: bounded needs a positive max_ratio for {code!r}", code
        )
    return ratio


def _qualify(code: str, concepts: list[str]) -> list[str]:
    """Each entry as `taxonomy:Concept`, or `taxonomy:A + taxonomy:B` for a summed concept. The
    members of a sum are distinct and share one taxonomy; no entry may repeat (a concept may recur
    as a member of another entry, which is how a sum falls back to its anchor alone)."""
    qualified = [_qualify_entry(code, c) for c in concepts]
    if len(set(qualified)) != len(qualified):
        raise MappingConfigError("duplicate concept", code)
    return qualified


def _qualify_entry(code: str, entry: str) -> str:
    members = signed_members(entry)
    names = [(taxonomy, concept) for _, taxonomy, concept in members]
    if any(not concept or not taxonomy for taxonomy, concept in names):
        raise MappingConfigError(f"empty member in {entry!r}", code)
    if any(_BAD_NAME.search(part) for name in names for part in name):  # `A + -B`, `A -B`
        raise MappingConfigError(f"malformed member in {entry!r}", code)
    if len(set(names)) != len(names):
        raise MappingConfigError(f"duplicate member in {entry!r}", code)
    if len({taxonomy for taxonomy, _ in names}) > 1:
        raise MappingConfigError(f"members of {entry!r} must share a taxonomy", code)
    return join_members(members)


def join_members(members: Sequence[tuple[int, str, str]]) -> str:
    """The text of an entry from its weighted members: `-taxonomy:A + taxonomy:B - taxonomy:C`.
    `signed_members` parses it back."""
    text = ""
    for at, (weight, taxonomy, concept) in enumerate(members):
        if at:
            text += " - " if weight < 0 else " + "
        elif weight < 0:
            text += "-"
        text += f"{taxonomy}:{concept}"
    return text


def _validate(items: list[CanonicalItemDef]) -> None:
    by_code: dict[str, CanonicalItemDef] = {}
    for item in items:
        if item.code in by_code:
            raise MappingConfigError("duplicate code", item.code)
        by_code[item.code] = item

    for item in items:
        if item.parent is not None:
            parent = by_code.get(item.parent)
            if parent is None:
                raise MappingConfigError(f"unknown parent {item.parent!r}", item.code)
            if parent.statement != item.statement:
                raise MappingConfigError(
                    f"parent {item.parent!r} is on another statement", item.code
                )
        if item.residual and (item.derive is None or item.concepts):
            raise MappingConfigError("a residual needs `derive` and no concepts", item.code)
        if item.derive is not None:
            for _, operand in parse_formula(item.derive):
                if operand not in by_code:
                    raise MappingConfigError(
                        f"formula references unknown code {operand!r}", item.code
                    )
                if by_code[operand].statement != item.statement:
                    raise MappingConfigError(
                        f"formula operand {operand!r} is on another statement", item.code
                    )

    for item in items:
        for _, covered in item.covers:
            for target in covered:
                other = by_code.get(target)
                if other is None:
                    raise MappingConfigError(f"covers unknown code {target!r}", item.code)
                if target == item.code:
                    raise MappingConfigError(
                        "a combined entry cannot cover the item itself", item.code
                    )
                if other.residual:
                    raise MappingConfigError(f"covers the residual {target!r}", item.code)
                if other.statement != item.statement:
                    raise MappingConfigError(
                        f"covers {target!r}, which is not on the same statement", item.code
                    )
                if other.kind != item.kind:
                    raise MappingConfigError(
                        f"covers {target!r}, which is not of the same kind", item.code
                    )

    for item in items:
        if item.forecast_fold is None:
            continue
        residual = by_code.get(item.forecast_fold)
        if residual is None or not residual.residual or residual.statement != item.statement:
            raise MappingConfigError(
                f"forecast_fold {item.forecast_fold!r} is not a residual of the same statement",
                item.code,
            )
        if item.code not in {c for _, c in parse_formula(residual.derive or "")}:
            raise MappingConfigError(
                f"forecast_fold {item.forecast_fold!r}: its formula does not hold the row",
                item.code,
            )

    for item in items:  # walk each parent chain: a cycle never reaches a root
        seen = {item.code}
        node = item
        while node.parent is not None:
            if node.parent in seen:
                raise MappingConfigError("parent cycle", item.code)
            seen.add(node.parent)
            node = by_code[node.parent]

    for item in items:
        for target, _ in item.rolls_into:
            if target not in by_code:
                raise MappingConfigError(f"rolls_into unknown code {target!r}", item.code)
            if by_code[target].statement != item.statement:
                raise MappingConfigError(
                    f"rolls_into target {target!r} is on another statement", item.code
                )
            if by_code[target].kind == "average":
                raise MappingConfigError(f"rolls_into target {target!r} is an average", item.code)

    for item in items:  # a delta must not come back to the line it started from
        pending = [t for t, _ in _edges(item)]
        reached: set[str] = set()
        while pending:
            code = pending.pop()
            if code == item.code:
                raise MappingConfigError("propagation cycle", item.code)
            if code not in reached:
                reached.add(code)
                pending.extend(t for t, _ in _edges(by_code[code]))

    formula_order(items)  # raises on a formula cycle
