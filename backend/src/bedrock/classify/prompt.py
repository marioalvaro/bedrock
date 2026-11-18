"""The instruction text and a question as text, shared by both adapters (docs/erd/face-tree.md
"Instruction text"). Pure."""

from decimal import Decimal

from bedrock.classify.types import LineQuestion
from bedrock.statements.structure import STATEMENT_NAMES

INSTRUCTIONS = (
    "You place one line of a company's filed financial statement on a fixed list of rows. "
    "Choose the row whose meaning is the same as the line's. If the line merges two or more of "
    "the rows into one amount, answer with each of them. If none of the rows is the line, answer "
    "none: the line then stays in the block's Other row, which is correct for any line that has "
    "no row of its own. A total or a subtotal of other lines is never a row on the list: answer "
    "none. Use the label first, then the tag name, the parent and the neighbouring lines; the "
    "amounts only show scale."
)
NONE = "none"


def render(question: LineQuestion) -> str:
    """One fact per line: statement, label, tag, filing, value, parent, block, neighbours, then
    the candidate rows as `code: label`."""
    lines = [
        f"Statement: {STATEMENT_NAMES.get(question.statement, question.statement)}",
        f"Label: {question.label}",
        f"Tag: {question.taxonomy}:{question.concept}",
        f"Filing: {question.form}, period ending {question.period_end.isoformat()}",
        f"Value: {_amount(question.value)}",
        f"Parent: {_parent(question)}",
        f"Block: {question.block_label or NONE}",
        f"Neighbouring lines: {'; '.join(question.sibling_labels) or NONE}",
        "Rows:",
    ]
    lines += [f"{c.code}: {c.label}" for c in question.candidates]
    return "\n".join(lines)


def _amount(value: Decimal | None) -> str:
    return NONE if value is None else format(value, "f")


def _parent(question: LineQuestion) -> str:
    if question.parent_label is None:
        return NONE
    if question.parent_value is None:
        return question.parent_label
    return f"{question.parent_label} ({_amount(question.parent_value)})"
