from pathlib import Path

import pytest

from bedrock.ratios.caveats import Caveat, load_caveats
from bedrock.ratios.registry import RegistryError

DE_TEXT = (
    "Consolidated figures include John Deere Financial. Its debt, interest expense and financing "
    "receivables fund customer purchases, so leverage, coverage and asset-based ratios are not "
    "comparable with an industrial company."
)
DE_CODES = frozenset(
    {
        "debt_to_ebitda",
        "net_debt_to_ebitda",
        "interest_coverage",
        "debt_to_equity",
        "roic",
        "roa",
        "asset_turnover",
        "dupont_asset_turnover",
        "dupont_equity_multiplier",
    }
)


DE_REVENUE_TEXT = (
    "Deere's revenue is net sales and revenues, which include John Deere Financial's finance and "
    "interest income, so gross margin and days sales outstanding are not comparable with an "
    "equipment maker's."
)


DE_EV_CODES = frozenset({"ev_sales", "ev_ebitda", "ev_ebit", "ev_fcf"})
DE_EV_TEXT = (
    "Enterprise value includes John Deere Financial's debt, which funds customer receivables, "
    "so EV multiples are not comparable with an industrial company's."
)


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "caveats.yaml"
    path.write_text(text)
    return path


def test_shipped_file_has_exactly_the_three_de_entries_in_order() -> None:
    assert load_caveats() == {
        "DE": (
            Caveat(codes=DE_CODES, text=DE_TEXT),
            Caveat(codes=frozenset({"gross_margin", "dso"}), text=DE_REVENUE_TEXT),
            Caveat(codes=DE_EV_CODES, text=DE_EV_TEXT),
        )
    }


def test_code_in_two_caveats_of_one_ticker_raises(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "DE:\n  - codes: [roe, roa]\n    text: one\n  - codes: [dso, roa]\n    text: two\n",
    )
    with pytest.raises(RegistryError, match="roa"):
        load_caveats(path)


def test_same_code_for_different_tickers_is_allowed(tmp_path: Path) -> None:
    path = write(
        tmp_path, "DE:\n  - codes: [roa]\n    text: one\nCAT:\n  - codes: [roa]\n    text: two\n"
    )
    assert set(load_caveats(path)) == {"DE", "CAT"}


def test_ticker_upper_cased_and_entries_kept_in_order(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "aapl:\n  - codes: [roe]\n    text: one\n  - codes: [roa, dso]\n    text: two\n",
    )
    assert load_caveats(path) == {
        "AAPL": (
            Caveat(codes=frozenset({"roe"}), text="one"),
            Caveat(codes=frozenset({"roa", "dso"}), text="two"),
        )
    }


def test_empty_file_means_no_caveats(tmp_path: Path) -> None:
    assert load_caveats(write(tmp_path, "")) == {}


def test_unknown_ratio_code_raises(tmp_path: Path) -> None:
    path = write(tmp_path, "DE:\n  - codes: [roe, bogus]\n    text: t\n")
    with pytest.raises(RegistryError, match="bogus"):
        load_caveats(path)


def test_empty_codes_raises(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="DE"):
        load_caveats(write(tmp_path, "DE:\n  - codes: []\n    text: t\n"))


@pytest.mark.parametrize("text", ['""', '"   "', "null"])
def test_empty_text_raises(tmp_path: Path, text: str) -> None:
    with pytest.raises(RegistryError, match="DE"):
        load_caveats(write(tmp_path, f"DE:\n  - codes: [roe]\n    text: {text}\n"))


@pytest.mark.parametrize(
    "content",
    [
        "- DE\n",  # not a mapping
        "DE: oops\n",  # entries not a list
        "DE:\n  - just text\n",  # entry not a mapping
        "DE:\n  - codes: roe\n    text: t\n",  # codes not a list
        "DE:\n  - codes: [1]\n    text: t\n",  # code not a string
        "DE:\n  - text: t\n",  # codes missing
        "DE:\n  - codes: [roe]\n    text: t\n    extra: 1\n",  # unknown key
        "DE:\n  - codes: [roe]\n    text: 5\n",  # text not a string
        "1:\n  - codes: [roe]\n    text: t\n",  # ticker not a string
        "DE:\n  - codes: [roe]\n    text: t\nde:\n  - codes: [roa]\n    text: u\n",  # dup ticker
    ],
)
def test_malformed_file_raises(tmp_path: Path, content: str) -> None:
    with pytest.raises(RegistryError):
        load_caveats(write(tmp_path, content))
