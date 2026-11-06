"""Valuation inputs: the catalog, parsing, derived defaults and per-case resolution
(docs/erd/valuation.md "Inputs (M5)"). Pure."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal

from bedrock.forecast.drivers import Bounds
from bedrock.forecast.resolve import ResolvedDrivers
from bedrock.ingest.manual_import import parse_number
from bedrock.valuation.interface import MarketData

InputKind = Literal["number", "integer", "choice", "bool", "comps_set"]
InputUnit = Literal["pct", "x", "year"]
InputValue = Decimal | int | str | bool
InputSource = Literal["own", "base", "default", "derived"]

D = Decimal
SOURCES = ("off", "manual", "own_history", "peer_median")
# multiple target code -> (label, default source)
TARGETS: dict[str, tuple[str, str]] = {
    "pe": ("P/E", "own_history"),
    "ev_ebitda": ("EV/EBITDA", "own_history"),
    "p_fcf": ("P/FCF", "off"),
    "ev_sales": ("EV/Sales", "off"),
}
NO_CLOSE = "No close: set the debt weight or a direct discount rate"
NO_SHARES = "No share count: set the debt weight or a direct discount rate"
NO_WEIGHTS = "No market weights: debt plus market value is not positive"
NO_INTEREST = "Risk-free rate: the forecast has no interest rate"


class InvalidInput(ValueError):
    """A valuation input code or text that is not allowed; the message says why."""


@dataclass(frozen=True)
class InputDef:
    code: str
    label: str
    group: str
    unit: InputUnit | None
    kind: InputKind
    choices: tuple[str, ...] | None = None
    bounds: Bounds | None = None
    default: InputValue | None = None
    derived: bool = False  # the default is derived from the forecast and the market


def _pct(low: str, high: str) -> Bounds:
    return Bounds(D(low), D(high))


_DISCOUNT, _TERMINAL, _MULTIPLES = "Discount rate", "Terminal value", "Multiples"
INPUTS: tuple[InputDef, ...] = (
    InputDef(
        "discount_method", "Discount method", _DISCOUNT, None, "choice", ("wacc", "direct"),
        default="wacc",
    ),
    InputDef(
        "discount_rate", "Discount rate", _DISCOUNT, "pct", "number", bounds=_pct("0.01", "0.5"),
        default=D("0.09"),
    ),
    InputDef(
        "risk_free_rate", "Risk-free rate", _DISCOUNT, "pct", "number", bounds=_pct("0", "0.2"),
        default=D("0.04"),
    ),
    InputDef(
        "equity_risk_premium", "Equity risk premium", _DISCOUNT, "pct", "number",
        bounds=_pct("0", "0.2"), default=D("0.05"),
    ),
    InputDef("beta", "Beta", _DISCOUNT, "x", "number", bounds=_pct("0", "5"), default=D(1)),
    InputDef(
        "cost_of_debt", "Cost of debt", _DISCOUNT, "pct", "number", bounds=_pct("0", "0.5"),
        derived=True,
    ),
    InputDef(
        "tax_rate", "Tax rate", _DISCOUNT, "pct", "number", bounds=_pct("0", "1"), derived=True
    ),
    InputDef(
        "debt_weight", "Debt weight", _DISCOUNT, "pct", "number", bounds=_pct("0", "0.99"),
        derived=True,
    ),
    InputDef(
        "terminal_method", "Terminal method", _TERMINAL, None, "choice",
        ("gordon", "exit_multiple"), default="gordon",
    ),
    InputDef(
        "terminal_growth", "Terminal growth", _TERMINAL, "pct", "number",
        bounds=_pct("-0.05", "0.1"), default=D("0.025"),
    ),
    InputDef(
        "exit_multiple", "Exit multiple (EV/EBITDA)", _TERMINAL, "x", "number",
        bounds=Bounds(D(0), D(100), low_open=True), default=D(12),
    ),
    InputDef("mid_year", "Mid-year discounting", _TERMINAL, None, "bool", default=True),
    *(
        InputDef(f"{m}_source", f"{label} source", _MULTIPLES, None, "choice", SOURCES,
                 default=source)
        for m, (label, source) in TARGETS.items()
    ),
    *(
        InputDef(f"{m}_multiple", f"{label} multiple", _MULTIPLES, "x", "number",
                 bounds=Bounds(D(0), D(1000), low_open=True))
        for m, (label, _) in TARGETS.items()
    ),
    *(
        InputDef(f"{m}_percentile", f"{label} percentile", _MULTIPLES, "pct", "number",
                 bounds=_pct("0", "1"), default=D("0.5"))
        for m, (label, _) in TARGETS.items()
    ),
    *(
        InputDef(f"{m}_year", f"{label} year", _MULTIPLES, "year", "integer",
                 bounds=Bounds(D(1), D(5)), default=1)
        for m, (label, _) in TARGETS.items()
    ),
    InputDef("comps_set_id", "Comps set", _MULTIPLES, None, "comps_set"),
)  # fmt: skip  # one input per line reads as the ERD table; the formatter splits each over 5
_BY_CODE = {d.code: d for d in INPUTS}


def input_def(code: str) -> InputDef:
    """Raises InvalidInput for a code that is not in the catalog."""
    if code not in _BY_CODE:
        raise InvalidInput(f"Unknown valuation input '{code}'")
    return _BY_CODE[code]


def parse_input(code: str, text: str) -> InputValue:
    """The typed value of an input's text: a number (no exponent notation, G21) within its
    bounds, a whole number within its bounds, one of the choices, `true`/`false`, or a positive
    comps set id. Raises InvalidInput with the message."""
    d = input_def(code)
    stripped = text.strip()
    if d.kind == "choice":
        assert d.choices is not None
        if stripped not in d.choices:
            raise InvalidInput(f"{code} must be one of {', '.join(d.choices)}")
        return stripped
    if d.kind == "bool":
        if stripped not in ("true", "false"):
            raise InvalidInput(f"{code} must be true or false")
        return stripped == "true"
    if d.kind == "comps_set":
        if not _digits(stripped) or int(stripped) <= 0:
            raise InvalidInput(f"{code} must be a comps set id")
        return int(stripped)
    if d.kind == "integer":
        if not _digits(stripped):
            raise InvalidInput(f"{code} must be a whole number")
        whole = int(stripped)
        _check(d, D(whole))
        return whole
    number = parse_number(stripped)
    if number is None:
        raise InvalidInput(f"{code} must be a number")
    _check(d, number)
    return number


def format_input(value: InputValue) -> str:
    """The stored text of a parsed value: a decimal as a plain string, `true`/`false`."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _digits(text: str) -> bool:
    return text.isascii() and text.isdecimal()


def _check(d: InputDef, value: Decimal) -> None:
    if d.bounds is not None and not d.bounds.contains(value):
        raise InvalidInput(f"{d.code} must be in {d.bounds}")


# -- derived defaults ------------------------------------------------------------------------


@dataclass(frozen=True)
class DerivedValue:
    """A derived default: its value (None when it cannot be computed), why, and the input whose
    resolved value it takes instead (`follows`)."""

    value: Decimal | None
    note: str | None
    follows: str | None = None


def derive(
    drivers: ResolvedDrivers | None, first_year: int, market: MarketData
) -> dict[str, DerivedValue]:
    """The derived defaults of `cost_of_debt`, `tax_rate` and `debt_weight` from the case's
    resolution (None when the forecast cannot run) at its first forecast year, and the market."""

    def driver(code: str) -> Decimal | None:
        if drivers is None or code not in drivers.codes:
            return None
        value = drivers.get(code, first_year).value
        return value if isinstance(value, Decimal) else None

    interest, tax = driver("interest_rate"), driver("tax_rate")
    return {
        "cost_of_debt": (
            DerivedValue(interest, f"From the forecast's FY{first_year} interest rate")
            if interest is not None and interest > 0
            else DerivedValue(None, NO_INTEREST, follows="risk_free_rate")
        ),
        "tax_rate": DerivedValue(
            tax,
            None
            if drivers is None
            else f"From the forecast's FY{first_year} tax rate"
            if tax is not None
            else f"The forecast has no FY{first_year} tax rate",
        ),
        "debt_weight": _debt_weight(market),
    }


def _debt_weight(market: MarketData) -> DerivedValue:
    if market.price is None or market.price_date is None:
        return DerivedValue(None, NO_CLOSE)
    if market.shares is None or market.shares <= 0:
        return DerivedValue(None, NO_SHARES)
    debt = market.bridge.total_debt
    total = debt + market.price * market.shares
    if total <= 0:
        return DerivedValue(None, NO_WEIGHTS)
    return DerivedValue(
        debt / total, f"Market weights at the close of {market.price_date.isoformat()}"
    )


# -- resolution ------------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedInput:
    code: str
    value: InputValue | None
    source: InputSource
    note: str | None = None


@dataclass(frozen=True)
class ResolvedInputs:
    rows: tuple[ResolvedInput, ...]  # catalog order

    def _row(self, code: str) -> ResolvedInput:
        for row in self.rows:
            if row.code == code:
                return row
        raise KeyError(code)

    def get(self, code: str) -> InputValue | None:
        """The typed value. Raises KeyError for a code that is not in the catalog."""
        return self._row(code).value

    def source(self, code: str) -> InputSource:
        return self._row(code).source

    def note(self, code: str) -> str | None:
        return self._row(code).note

    def with_values(self, values: Mapping[str, InputValue]) -> "ResolvedInputs":
        """A copy with these values replaced (sources and notes kept): a sensitivity point."""
        return ResolvedInputs(
            tuple(replace(r, value=values[r.code]) if r.code in values else r for r in self.rows)
        )


def resolve_inputs(
    base_rows: Mapping[str, str],
    own_rows: Mapping[str, str],
    is_base: bool,
    derived: Mapping[str, DerivedValue],
) -> ResolvedInputs:
    """Each input: the case's own row → (Bull, Bear) Base's row → the default, or the derived
    value for a derived default (a derived value that `follows` an input takes its resolved
    value). Rows are stored texts by code. Raises InvalidInput for a row that does not parse."""
    rows: list[ResolvedInput] = []
    resolved: dict[str, InputValue | None] = {}
    for d in INPUTS:
        if d.code in own_rows:
            row = ResolvedInput(d.code, parse_input(d.code, own_rows[d.code]), "own")
        elif not is_base and d.code in base_rows:
            row = ResolvedInput(d.code, parse_input(d.code, base_rows[d.code]), "base")
        elif d.derived:
            found = derived.get(d.code, DerivedValue(None, None))
            value = resolved.get(found.follows) if found.follows is not None else found.value
            row = ResolvedInput(d.code, value, "derived", found.note)
        else:
            row = ResolvedInput(d.code, d.default, "default")
        resolved[d.code] = row.value
        rows.append(row)
    return ResolvedInputs(tuple(rows))
