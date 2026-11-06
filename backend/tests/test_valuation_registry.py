"""The valuation method registry (docs/erd/valuation.md "Interface" → Registry, FR-VAL-05) and
the engine purity rule (CLAUDE.md "Invariants")."""

import ast
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

from bedrock.valuation.inputs import ResolvedInputs, resolve_inputs
from bedrock.valuation.interface import MarketData, ValuationForecast, ValuationResult
from bedrock.valuation.registry import METHODS, run_methods
from tests.valuation_data import annual_forecast, flows, forecast, market

D = Decimal
SRC = Path(__file__).parents[1] / "src" / "bedrock"


def _inputs(**texts: str) -> ResolvedInputs:
    base = {
        "discount_method": "direct",
        "pe_source": "manual",
        "pe_multiple": "10",
        "ev_ebitda_source": "off",
    }
    return resolve_inputs({}, {**base, **texts}, is_base=True, derived={})


def _forecast() -> ValuationForecast:
    lines = {y: flows(100, 10, net_income_common=50) for y in range(2026, 2031)}
    return forecast(annual_forecast(lines))


def test_run_methods_returns_the_dcf_then_the_targets_in_order() -> None:
    inputs = _inputs(ev_ebitda_source="manual", ev_ebitda_multiple="8", ev_sales_source="off")
    results = run_methods(_forecast(), market(), inputs)
    assert [r.key for r in results] == ["dcf_fcff", "multiple:pe", "multiple:ev_ebitda"]
    assert [m.code for m in METHODS] == ["dcf_fcff", "multiple_target"]


class _Book:
    code: ClassVar[str] = "book_value"

    def value(
        self, forecast: ValuationForecast, market: MarketData, inputs: ResolvedInputs
    ) -> list[ValuationResult]:
        equity = forecast.statements.get("net_income_common", "FY2026") or D(0)
        return [ValuationResult("book", self.code, "Book", None, equity, equity, None, None)]


def test_a_method_passed_in_is_run_with_no_other_change() -> None:
    results = run_methods(_forecast(), market(), _inputs(), methods=(*METHODS, _Book()))
    assert [r.key for r in results] == ["dcf_fcff", "multiple:pe", "book"]
    assert results[-1].equity_value == D(50)
    only = run_methods(_forecast(), market(), _inputs(), methods=(_Book(),))
    assert [r.key for r in only] == ["book"]


FORBIDDEN = (
    "bedrock.services",
    "bedrock.api",
    "bedrock.models",
    "bedrock.repositories",
    "bedrock.schemas",
    "bedrock.core",
    "bedrock.ingest.sources",
    "bedrock.ingest.http",
    "bedrock.ingest.cache",
    "sqlalchemy",
    "fastapi",
    "httpx",
)


def _imports(path: Path) -> set[str]:
    """Every module a file imports, `from a import b` as both `a` and `a.b`; a relative import as
    `.` (the engines import absolutely)."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                found.add(".")
                continue
            module = node.module or ""
            found.add(module)
            found |= {f"{module}.{alias.name}" for alias in node.names}
    return found


def test_the_import_scan_sees_every_import_form(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("from bedrock import services\nfrom . import x\nimport sqlalchemy.orm\n")
    assert {"bedrock.services", ".", "sqlalchemy.orm"} <= _imports(sample)


def test_the_valuation_engines_import_no_service_api_db_or_network_code() -> None:
    files = [*(SRC / "valuation").glob("*.py"), SRC / "forecast" / "perturb.py"]
    assert len(files) >= 8
    for path in files:
        bad = [m for m in _imports(path) if m.startswith(FORBIDDEN) or m == "."]
        assert not bad, f"{path.name} imports {bad}"
