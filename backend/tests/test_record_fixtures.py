import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "record_fixtures.py"


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location("record_fixtures", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _spy(monkeypatch: pytest.MonkeyPatch, script: ModuleType) -> list[tuple[str, list[str]]]:
    calls: list[tuple[str, list[str]]] = []
    for kind in ("edgar", "prices", "splits"):
        monkeypatch.setattr(
            script, f"record_{kind}", lambda tickers, kind=kind: calls.append((kind, tickers))
        )
    return calls


def test_by_default_every_kind_is_recorded(
    monkeypatch: pytest.MonkeyPatch, script: ModuleType
) -> None:
    calls = _spy(monkeypatch, script)

    assert script.main(["aapl", "DE"]) == 0

    assert calls == [
        ("edgar", ["AAPL", "DE"]),
        ("prices", ["AAPL", "DE"]),
        ("splits", ["AAPL", "DE"]),
    ]


def test_only_splits_records_only_splits(
    monkeypatch: pytest.MonkeyPatch, script: ModuleType
) -> None:
    calls = _spy(monkeypatch, script)

    assert script.main(["--only", "splits", "AAPL"]) == 0

    assert calls == [("splits", ["AAPL"])]


def test_only_is_repeatable(monkeypatch: pytest.MonkeyPatch, script: ModuleType) -> None:
    calls = _spy(monkeypatch, script)

    script.main(["--only", "splits", "--only", "prices", "COST"])

    assert calls == [("prices", ["COST"]), ("splits", ["COST"])]


def test_no_tickers_prints_usage_and_records_nothing(
    monkeypatch: pytest.MonkeyPatch, script: ModuleType
) -> None:
    calls = _spy(monkeypatch, script)

    assert script.main([]) == 2
    assert calls == []


def test_ratios_are_written_as_plain_decimals(script: ModuleType) -> None:
    assert [script.format_ratio(r) for r in (7.0, 2.0, 0.1, 1.5, 20.0)] == [
        "7",
        "2",
        "0.1",
        "1.5",
        "20",
    ]
