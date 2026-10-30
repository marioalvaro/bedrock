"""The concept triage file (FR-DATA-13): a verdict per unmapped concept, loaded and validated."""

from pathlib import Path

import pytest

from bedrock.mapping.config import (
    DEFAULT_ITEMS_PATH,
    MappingConfigError,
    load_canonical_items,
)
from bedrock.mapping.triage import (
    DEFAULT_TRIAGE_PATH,
    TRIAGE_TYPES,
    ConceptVerdict,
    load_concept_triage,
)
from tests.engine_data import item

ITEMS = [
    item("long_term_debt", "BS", kind="instant", concepts=["us-gaap:LongTermDebtNoncurrent"]),
    item("short_term_debt", "BS", kind="instant", concepts=["us-gaap:DebtCurrent + ifrs:Lease"]),
    item("interest_expense", concepts=["us-gaap:InterestExpense"]),
    item("ppe_net", "BS", kind="instant"),
    item(
        "other_current_liabilities",
        "BS",
        kind="instant",
        derive="short_term_debt - long_term_debt",
        residual=True,
    ),
]


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "triage.yaml"
    path.write_text(text)
    return path


def load(tmp_path: Path, text: str):  # type: ignore[no-untyped-def]
    return load_concept_triage(write(tmp_path, text), ITEMS)


VALID = """
YearTwoLadder: {type: disclosure, reason: debt maturity schedule}
Land: {type: component, codes: [ppe_net], reason: gross PP&E component}
InterestPaidNet: {type: rejected, codes: [interest_expense], reason: "cash paid, not the expense"}
LongTermDebt: {type: scope, codes: [long_term_debt], reason: includes the current portion}
IncreaseDecreaseInReceivables: {type: candidate, codes: [ppe_net], reason: to verify}
"aapl:OddGain": {type: disclosure, reason: a company extension tag}
"""


def test_a_valid_file_loads_one_verdict_per_concept_with_bare_names_meaning_us_gaap(
    tmp_path: Path,
) -> None:
    triage = load(tmp_path, VALID)

    assert triage[("us-gaap", "Land")] == ConceptVerdict(
        "component", "gross PP&E component", ("ppe_net",)
    )
    assert triage[("us-gaap", "InterestPaidNet")].codes == ("interest_expense",)
    assert triage[("aapl", "OddGain")] == ConceptVerdict(
        "disclosure", "a company extension tag", ()
    )
    assert len(triage) == 6


def test_the_five_types_are_the_ones_of_the_erd() -> None:
    assert TRIAGE_TYPES == ("disclosure", "component", "rejected", "scope", "candidate")


def test_a_disclosure_needs_no_codes(tmp_path: Path) -> None:
    triage = load(tmp_path, "Foo: {type: disclosure, reason: a note schedule}")

    assert triage[("us-gaap", "Foo")].codes == ()


def test_an_empty_file_is_an_empty_triage(tmp_path: Path) -> None:
    assert load(tmp_path, "") == {}


def test_a_file_that_is_not_a_mapping_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(MappingConfigError, match="must map concepts to verdicts"):
        load(tmp_path, "- just\n- a list\n")


def test_an_unknown_type_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(MappingConfigError, match="Foo.*type"):
        load(tmp_path, "Foo: {type: maybe, codes: [ppe_net], reason: because}")


def test_a_missing_type_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(MappingConfigError, match="Foo.*type"):
        load(tmp_path, "Foo: {codes: [ppe_net], reason: because}")


def test_an_unknown_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(MappingConfigError, match="Foo.*unknown key.*note"):
        load(tmp_path, "Foo: {type: component, codes: [ppe_net], reason: because, note: x}")


def test_a_verdict_that_is_not_a_mapping_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(MappingConfigError, match="Foo.*verdict"):
        load(tmp_path, "Foo: component")


@pytest.mark.parametrize("reason", ["", "'   '", "null"])
def test_a_missing_or_blank_reason_is_rejected(tmp_path: Path, reason: str) -> None:
    with pytest.raises(MappingConfigError, match="Foo.*reason"):
        load(tmp_path, f"Foo: {{type: disclosure, reason: {reason}}}")


def test_a_verdict_without_a_reason_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(MappingConfigError, match="Foo.*reason"):
        load(tmp_path, "Foo: {type: component, codes: [ppe_net]}")


@pytest.mark.parametrize("kind", ["component", "rejected", "scope", "candidate"])
def test_every_type_but_disclosure_needs_codes(tmp_path: Path, kind: str) -> None:
    with pytest.raises(MappingConfigError, match="Foo.*codes"):
        load(tmp_path, f"Foo: {{type: {kind}, reason: because}}")
    with pytest.raises(MappingConfigError, match="Foo.*codes"):
        load(tmp_path, f"Foo: {{type: {kind}, codes: [], reason: because}}")


def test_an_unknown_code_is_rejected_even_on_a_disclosure(tmp_path: Path) -> None:
    with pytest.raises(MappingConfigError, match="Foo.*unknown code 'nope'"):
        load(tmp_path, "Foo: {type: component, codes: [ppe_net, nope], reason: because}")
    with pytest.raises(MappingConfigError, match="Foo.*unknown code 'nope'"):
        load(tmp_path, "Foo: {type: disclosure, codes: [nope], reason: because}")


def test_codes_must_be_a_list_of_strings(tmp_path: Path) -> None:
    with pytest.raises(MappingConfigError, match="Foo.*codes"):
        load(tmp_path, "Foo: {type: component, codes: ppe_net, reason: because}")


def test_a_duplicate_concept_is_rejected_also_across_spellings(tmp_path: Path) -> None:
    same_key = "Foo: {type: disclosure, reason: one}\nFoo: {type: disclosure, reason: two}\n"
    with pytest.raises(MappingConfigError, match="duplicate concept.*Foo"):
        load(tmp_path, same_key)
    with pytest.raises(MappingConfigError, match="duplicate concept.*Foo"):
        load(
            tmp_path,
            "Foo: {type: disclosure, reason: one}\n"
            "'us-gaap:Foo': {type: disclosure, reason: two}\n",
        )


def test_a_default_concept_cannot_have_a_verdict(tmp_path: Path) -> None:
    with pytest.raises(MappingConfigError, match="InterestExpense.*default"):
        load(tmp_path, "InterestExpense: {type: rejected, codes: [ppe_net], reason: because}")


def test_a_member_of_a_summed_default_cannot_have_a_verdict(tmp_path: Path) -> None:
    with pytest.raises(MappingConfigError, match="DebtCurrent.*default"):
        load(tmp_path, "DebtCurrent: {type: scope, codes: [short_term_debt], reason: because}")
    with pytest.raises(MappingConfigError, match="ifrs:Lease.*default|ifrs-full:Lease.*default"):
        load(tmp_path, "'ifrs:Lease': {type: scope, codes: [short_term_debt], reason: because}")


def test_a_concept_that_is_only_a_company_override_may_have_a_verdict(tmp_path: Path) -> None:
    # Overrides are per company, and that company maps the concept, so it never shows as unmapped
    # there; for the others it is unmapped, and the verdict is about the concept.
    triage = load(tmp_path, "OverrideOnly: {type: scope, codes: [ppe_net], reason: because}")

    assert ("us-gaap", "OverrideOnly") in triage


def test_the_shipped_file_loads_against_the_shipped_items_and_has_no_candidate() -> None:
    items = load_canonical_items(DEFAULT_ITEMS_PATH)

    triage = load_concept_triage(DEFAULT_TRIAGE_PATH, items)

    assert triage
    assert [k for k, v in triage.items() if v.type == "candidate"] == []
