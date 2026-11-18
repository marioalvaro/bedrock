"""The instruction text and the rendering of a question (M7d S2, docs/erd/face-tree.md
"Instruction text"): shared by both adapters."""

from datetime import date
from decimal import Decimal

from bedrock.classify import prompt
from tests.classify_data import question


def test_the_instructions_are_the_erd_text_verbatim() -> None:
    assert prompt.INSTRUCTIONS == (
        "You place one line of a company's filed financial statement on a fixed list of rows. "
        "Choose the row whose meaning is the same as the line's. If the line merges two or more "
        "of the rows into one amount, answer with each of them. If none of the rows is the line, "
        "answer none: the line then stays in the block's Other row, which is correct for any line "
        "that has no row of its own. A total or a subtotal of other lines is never a row on the "
        "list: answer none. Use the label first, then the tag name, the parent and the "
        "neighbouring lines; the amounts only show scale."
    )


def test_render_writes_one_fact_per_line_then_the_candidates() -> None:
    assert prompt.render(question()).splitlines() == [
        "Statement: balance sheet",
        "Label: Label of Widgets",
        "Tag: ext:Widgets",
        "Filing: 10-K, period ending 2023-12-31",
        "Value: 5000000",
        "Parent: Total current assets (18000000)",
        "Block: Total current assets",
        "Neighbouring lines: Cash and cash equivalents; Other current assets",
        "Rows:",
        "cash: Cash",
        "inventory: Inventory",
    ]


def test_render_says_what_is_missing() -> None:
    bare = question(
        statement="IS",
        value=None,
        parent_label=None,
        parent_value=None,
        sibling_labels=(),
        block_label=None,
        candidates=(),
    )

    assert prompt.render(bare).splitlines() == [
        "Statement: income statement",
        "Label: Label of Widgets",
        "Tag: ext:Widgets",
        "Filing: 10-K, period ending 2023-12-31",
        "Value: none",
        "Parent: none",
        "Block: none",
        "Neighbouring lines: none",
        "Rows:",
    ]


def test_render_writes_a_parent_without_a_value_by_its_label_only() -> None:
    rendered = prompt.render(question(parent_value=None))

    assert "Parent: Total current assets" in rendered.splitlines()


def test_render_writes_amounts_as_plain_numbers() -> None:
    rendered = prompt.render(
        question(value=Decimal("1.5E+9"), parent_value=Decimal("-2500.50"), form="10-Q")
    )

    assert "Value: 1500000000" in rendered.splitlines()
    assert "Parent: Total current assets (-2500.50)" in rendered.splitlines()
    assert "Filing: 10-Q, period ending 2023-12-31" in rendered.splitlines()


def test_render_is_one_question_per_call() -> None:
    first = prompt.render(question("A", period_end=date(2022, 12, 31)))
    assert "Tag: ext:A" in first and "2022-12-31" in first
