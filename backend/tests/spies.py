"""Call counters for cost tests: the work a request does, asserted instead of its wall-clock time
(docs/erd/platform.md "Testing Strategy" rule 4, Gotcha G42)."""

from functools import wraps
from typing import Any

import pytest


def count_calls(monkeypatch: pytest.MonkeyPatch, owner: Any, name: str) -> list[int]:
    """Wrap `owner.name` (a module function or a class's method) so each call appends to the
    returned list; the real function still runs."""
    calls: list[int] = []
    real = getattr(owner, name)

    @wraps(real)
    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(owner, name, counting)
    return calls
