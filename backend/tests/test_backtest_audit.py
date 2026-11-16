"""The audit diff (docs/erd/accountability.md "Audit trail"). Pure."""

from bedrock.backtest.audit import FieldChange, changes


def test_equal_values_give_nothing() -> None:
    assert changes({"a": "1", "b": None}, {"a": "1", "b": None}) == []


def test_nothing_on_either_side_gives_nothing() -> None:
    assert changes({}, {}) == []


def test_an_absent_field_equals_none() -> None:
    assert changes({"a": None}, {}) == []
    assert changes({}, {"a": None}) == []


def test_an_added_field_has_no_old_value() -> None:
    assert changes({}, {"a": "1"}) == [FieldChange("a", None, "1")]


def test_a_removed_field_has_no_new_value() -> None:
    assert changes({"a": "1"}, {}) == [FieldChange("a", "1", None)]


def test_a_changed_field_has_both() -> None:
    assert changes({"a": "1"}, {"a": "2"}) == [FieldChange("a", "1", "2")]


def test_changes_are_sorted_by_field() -> None:
    before = {"c": "1", "a": "1"}
    after = {"c": "2", "b": "1", "a": "2"}
    assert [c.field for c in changes(before, after)] == ["a", "b", "c"]
