"""The ratio library as data (FR-ANL-01..04): named metrics and ratio definitions. Pure.

`RATIOS` is the table of docs/erd/analysis.md "Definitions (M2)" in display order. Import-time
checks reject a duplicate code, an operand that is neither a canonical code, a metric nor a ratio,
and a cycle among metrics or ratios (`RegistryError`).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from bedrock.mapping.config import MappingConfigError, load_canonical_items, parse_formula

Unit = Literal["pct", "x", "days", "USD/shares"]
Category = Literal["Profitability", "DuPont", "Liquidity", "Solvency", "Efficiency", "Per share"]


class RegistryError(ValueError):
    """The registry is inconsistent; the message names the offending code."""


@dataclass(frozen=True)
class Metric:
    """A named intermediate (`ebitda`, `tax_rate`, `nopat`, `invested_capital`).

    `inputs` are the operand codes `fn` reads (canonical codes or other metrics); `fn` gets their
    values for one point in time and returns the metric, or None. A None input reaches `fn`, which
    decides (every shipped metric returns None for a None input)."""

    code: str
    label: str
    inputs: tuple[str, ...]
    fn: Callable[[Mapping[str, Decimal | None]], Decimal | None]


@dataclass(frozen=True, kw_only=True)
class Ratio:
    """One ratio row. `numerator`/`denominator` are operands: a canonical, metric or ratio code,
    or a formula of them joined by `+`/`-` (`mapping/config.py::parse_formula`). No denominator:
    the ratio is the numerator. `avg_*` averages that whole operand over the period's two ends.
    `scale` multiplies the result. `ttm` replaces (numerator, denominator) in TTM. `definition`
    is the ERD table's "Definition" text, sent by the API."""

    code: str
    label: str
    category: Category
    unit: Unit
    definition: str
    numerator: str
    denominator: str | None = None
    avg_numerator: bool = False
    avg_denominator: bool = False
    scale: Decimal = Decimal(1)
    ttm: tuple[str, str | None] | None = None


def _known(values: Mapping[str, Decimal | None], codes: tuple[str, ...]) -> list[Decimal] | None:
    """The values of `codes` in order, or None when any is missing."""
    picked = [values.get(code) for code in codes]
    return None if any(v is None for v in picked) else [v for v in picked if v is not None]


def _ebitda(values: Mapping[str, Decimal | None]) -> Decimal | None:
    got = _known(values, ("operating_income", "d_and_a"))
    return None if got is None else got[0] + got[1]


def _tax_rate(values: Mapping[str, Decimal | None]) -> Decimal | None:
    got = _known(values, ("income_tax", "pretax_income"))
    if got is None or got[1] <= 0:
        return None
    return min(max(got[0] / got[1], Decimal(0)), Decimal(1))


def _nopat(values: Mapping[str, Decimal | None]) -> Decimal | None:
    got = _known(values, ("operating_income", "tax_rate"))
    return None if got is None else got[0] * (1 - got[1])


def _invested_capital(values: Mapping[str, Decimal | None]) -> Decimal | None:
    got = _known(values, ("total_debt", "total_equity", "cash", "short_term_investments"))
    return None if got is None else got[0] + got[1] - got[2] - got[3]


METRICS: tuple[Metric, ...] = (
    Metric("ebitda", "EBITDA", ("operating_income", "d_and_a"), _ebitda),
    Metric("tax_rate", "Effective tax rate", ("income_tax", "pretax_income"), _tax_rate),
    Metric("nopat", "NOPAT", ("operating_income", "tax_rate"), _nopat),
    Metric(
        "invested_capital",
        "Invested capital",
        ("total_debt", "total_equity", "cash", "short_term_investments"),
        _invested_capital,
    ),
)

_DAYS = Decimal(365)

RATIOS: tuple[Ratio, ...] = (
    # Profitability
    Ratio(
        code="gross_margin",
        label="Gross margin",
        category="Profitability",
        unit="pct",
        definition="gross_profit ÷ revenue",
        numerator="gross_profit",
        denominator="revenue",
    ),
    Ratio(
        code="operating_margin",
        label="Operating margin",
        category="Profitability",
        unit="pct",
        definition="operating_income ÷ revenue",
        numerator="operating_income",
        denominator="revenue",
    ),
    Ratio(
        code="ebitda_margin",
        label="EBITDA margin",
        category="Profitability",
        unit="pct",
        definition="ebitda ÷ revenue",
        numerator="ebitda",
        denominator="revenue",
    ),
    Ratio(
        code="net_margin",
        label="Net margin",
        category="Profitability",
        unit="pct",
        definition="net_income_common ÷ revenue",
        numerator="net_income_common",
        denominator="revenue",
    ),
    Ratio(
        code="fcf_margin",
        label="FCF margin",
        category="Profitability",
        unit="pct",
        definition="free_cash_flow ÷ revenue",
        numerator="free_cash_flow",
        denominator="revenue",
    ),
    Ratio(
        code="roe",
        label="Return on equity",
        category="Profitability",
        unit="pct",
        definition="net_income_common ÷ avg(equity_parent)",
        numerator="net_income_common",
        denominator="equity_parent",
        avg_denominator=True,
    ),
    Ratio(
        code="roa",
        label="Return on assets",
        category="Profitability",
        unit="pct",
        definition="net_income ÷ avg(total_assets)",
        numerator="net_income",
        denominator="total_assets",
        avg_denominator=True,
    ),
    Ratio(
        code="roic",
        label="Return on invested capital",
        category="Profitability",
        unit="pct",
        definition="nopat ÷ avg(invested_capital)",
        numerator="nopat",
        denominator="invested_capital",
        avg_denominator=True,
    ),
    # DuPont
    Ratio(
        code="dupont_net_margin",
        label="Net margin",
        category="DuPont",
        unit="pct",
        definition="net_income_common ÷ revenue",
        numerator="net_income_common",
        denominator="revenue",
    ),
    Ratio(
        code="dupont_asset_turnover",
        label="Asset turnover",
        category="DuPont",
        unit="x",
        definition="revenue ÷ avg(total_assets)",
        numerator="revenue",
        denominator="total_assets",
        avg_denominator=True,
    ),
    Ratio(
        code="dupont_equity_multiplier",
        label="Equity multiplier",
        category="DuPont",
        unit="x",
        definition="avg(total_assets) ÷ avg(equity_parent)",
        numerator="total_assets",
        denominator="equity_parent",
        avg_numerator=True,
        avg_denominator=True,
    ),
    # Liquidity
    Ratio(
        code="current_ratio",
        label="Current ratio",
        category="Liquidity",
        unit="x",
        definition="total_current_assets ÷ total_current_liabilities",
        numerator="total_current_assets",
        denominator="total_current_liabilities",
    ),
    Ratio(
        code="quick_ratio",
        label="Quick ratio",
        category="Liquidity",
        unit="x",
        definition="(cash + short_term_investments + receivables) ÷ total_current_liabilities",
        numerator="cash + short_term_investments + receivables",
        denominator="total_current_liabilities",
    ),
    # Solvency
    Ratio(
        code="debt_to_ebitda",
        label="Debt / EBITDA",
        category="Solvency",
        unit="x",
        definition="total_debt ÷ ebitda",
        numerator="total_debt",
        denominator="ebitda",
    ),
    Ratio(
        code="net_debt_to_ebitda",
        label="Net debt / EBITDA",
        category="Solvency",
        unit="x",
        definition="net_debt ÷ ebitda",
        numerator="net_debt",
        denominator="ebitda",
    ),
    Ratio(
        code="interest_coverage",
        label="Interest coverage",
        category="Solvency",
        unit="x",
        definition="operating_income ÷ interest_expense",
        numerator="operating_income",
        denominator="interest_expense",
    ),
    Ratio(
        code="debt_to_equity",
        label="Debt / equity",
        category="Solvency",
        unit="x",
        definition="total_debt ÷ total_equity",
        numerator="total_debt",
        denominator="total_equity",
    ),
    # Efficiency
    Ratio(
        code="asset_turnover",
        label="Asset turnover",
        category="Efficiency",
        unit="x",
        definition="revenue ÷ avg(total_assets)",
        numerator="revenue",
        denominator="total_assets",
        avg_denominator=True,
    ),
    Ratio(
        code="dso",
        label="Days sales outstanding",
        category="Efficiency",
        unit="days",
        definition="avg(receivables) ÷ revenue × 365",
        numerator="receivables",
        denominator="revenue",
        avg_numerator=True,
        scale=_DAYS,
    ),
    Ratio(
        code="dio",
        label="Days inventory outstanding",
        category="Efficiency",
        unit="days",
        definition="avg(inventory) ÷ cost_of_revenue × 365",
        numerator="inventory",
        denominator="cost_of_revenue",
        avg_numerator=True,
        scale=_DAYS,
    ),
    Ratio(
        code="dpo",
        label="Days payables outstanding",
        category="Efficiency",
        unit="days",
        definition="avg(accounts_payable) ÷ cost_of_revenue × 365",
        numerator="accounts_payable",
        denominator="cost_of_revenue",
        avg_numerator=True,
        scale=_DAYS,
    ),
    Ratio(
        code="ccc",
        label="Cash conversion cycle",
        category="Efficiency",
        unit="days",
        definition="dso + dio − dpo (null unless all three exist)",
        numerator="dso + dio - dpo",
    ),
    # Per share
    Ratio(
        code="eps_diluted",
        label="EPS (diluted)",
        category="Per share",
        unit="USD/shares",
        definition="annual: the IS `eps_diluted` line; TTM: net_income_common ÷ shares_diluted",
        numerator="eps_diluted",  # the canonical IS line (canonical codes resolve first)
        ttm=("net_income_common", "shares_diluted"),
    ),
    Ratio(
        code="fcf_per_share",
        label="FCF per share",
        category="Per share",
        unit="USD/shares",
        definition="free_cash_flow ÷ shares_diluted",
        numerator="free_cash_flow",
        denominator="shares_diluted",
    ),
    Ratio(
        code="bvps",
        label="Book value per share",
        category="Per share",
        unit="USD/shares",
        definition="equity_parent ÷ shares_outstanding",
        numerator="equity_parent",
        denominator="shares_outstanding",
    ),
    Ratio(
        code="dps",
        label="Dividends per share",
        category="Per share",
        unit="USD/shares",
        definition="dividends_per_share (TTM: the TTM sum)",
        numerator="dividends_per_share",
    ),
)


def operand_codes(operand: str) -> list[str]:
    """The codes a numerator/denominator text reads, in order (`a + b - c` -> [a, b, c]).

    Raises `RegistryError` for a text that is not a `+`/`-` formula of codes."""
    try:
        return [code for _, code in parse_formula(operand)]
    except MappingConfigError as exc:
        raise RegistryError(str(exc)) from exc


def _ratio_operands(ratio: Ratio) -> list[str]:
    """Every operand text of `ratio`, the `ttm` replacements included."""
    texts = [ratio.numerator, ratio.denominator]
    if ratio.ttm is not None:
        texts.extend(ratio.ttm)
    return [text for text in texts if text is not None]


def _reject_cycle(kind: str, edges: Mapping[str, list[str]]) -> None:
    """Depth-first search over `edges` (code -> codes of the same kind it reads)."""
    done: set[str] = set()

    def visit(code: str, path: list[str]) -> None:
        if code in path:
            cycle = " -> ".join([*path[path.index(code) :], code])
            raise RegistryError(f"{code}: {kind} cycle {cycle}")
        if code in done:
            return
        for target in edges[code]:
            visit(target, [*path, code])
        done.add(code)

    for code in edges:
        visit(code, [])


def validate(
    metrics: tuple[Metric, ...], ratios: tuple[Ratio, ...], canonical_codes: frozenset[str]
) -> None:
    """Raise `RegistryError` for a duplicate code (across metrics and ratios), an operand or metric
    input that is not a canonical code / metric / ratio, or a cycle among metrics or ratios
    (including through the `ttm` operands). Called at import on `METRICS` and `RATIOS`.

    Names resolve canonical code -> metric -> ratio. A metric must not shadow a canonical code,
    and metric and ratio codes must not collide. A ratio code may equal a canonical code
    (`eps_diluted`): an operand with that name means the canonical line, so a ratio reading its
    own canonical line is not a self-cycle. A metric input is a canonical code or a metric
    (metrics are evaluated before ratios)."""
    seen: set[str] = set()
    for code in [m.code for m in metrics] + [r.code for r in ratios]:
        if code in seen:
            raise RegistryError(f"{code}: duplicate metric/ratio code")
        seen.add(code)
    metric_codes = {m.code for m in metrics}
    ratio_codes = {r.code for r in ratios}

    metric_edges: dict[str, list[str]] = {}
    for m in metrics:
        if m.code in canonical_codes:
            raise RegistryError(f"{m.code}: metric shadows a canonical code")
        for code in m.inputs:
            if code not in canonical_codes and code not in metric_codes:
                raise RegistryError(f"{m.code}: unknown metric input {code!r}")
        metric_edges[m.code] = [c for c in m.inputs if c not in canonical_codes]

    ratio_edges: dict[str, list[str]] = {}
    for r in ratios:
        targets: list[str] = []
        for text in _ratio_operands(r):
            try:
                codes = operand_codes(text)
            except RegistryError as exc:
                raise RegistryError(f"{r.code}: {exc}") from exc
            for code in codes:
                if code in canonical_codes or code in metric_codes:
                    continue
                if code not in ratio_codes:
                    raise RegistryError(f"{r.code}: unknown operand {code!r}")
                targets.append(code)
        ratio_edges[r.code] = targets

    _reject_cycle("metric", metric_edges)
    _reject_cycle("ratio", ratio_edges)


# The canonical line codes, read once from the shipped YAML; the calculator resolves names with it.
CANONICAL_CODES: frozenset[str] = frozenset(item.code for item in load_canonical_items())

validate(METRICS, RATIOS, CANONICAL_CODES)
