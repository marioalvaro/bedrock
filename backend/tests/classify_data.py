"""Hand-built questions for the classifier tests (M7d S2): no network, no DB."""

from datetime import date
from decimal import Decimal

from bedrock.classify.types import Candidate, LineQuestion


def question(concept: str = "Widgets", **changes: object) -> LineQuestion:
    fields: dict[str, object] = {
        "key": f"BS|ext|{concept}",
        "statement": "BS",
        "taxonomy": "ext",
        "concept": concept,
        "label": f"Label of {concept}",
        "form": "10-K",
        "period_end": date(2023, 12, 31),
        "value": Decimal("5000000"),
        "parent_label": "Total current assets",
        "parent_value": Decimal("18000000"),
        "sibling_labels": ("Cash and cash equivalents", "Other current assets"),
        "block_label": "Total current assets",
        "candidates": (Candidate("cash", "Cash"), Candidate("inventory", "Inventory")),
    }
    fields.update(changes)
    return LineQuestion(**fields)  # type: ignore[arg-type]
