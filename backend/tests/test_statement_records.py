"""`statements/records.py::records`: the rows of a frame as plain dicts, exactly as
`DataFrame.to_dict("records")` gives them, read column by column (the statements build's hot
loop)."""

from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd

from bedrock.statements.records import records


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": ["revenue", "net_income", "assets"],
            "period_start": [date(2024, 1, 1), date(2024, 1, 1), None],
            "period_end": [date(2024, 12, 31)] * 3,
            "value": pd.Series([Decimal("1.5"), Decimal("-2"), None], dtype="object"),
            "rank": [0, 1, 2],
            "share": [0.5, np.nan, 1.25],
            "filed_at": pd.to_datetime(["2025-02-01", None, "2025-02-03"]),
            "split_dates": pd.Series([(), (date(2020, 8, 31),), ()], dtype="object"),
        }
    )


def test_records_equal_to_dict_records_with_the_same_types() -> None:
    frame = _frame()
    expected = frame.to_dict("records")

    got = records(frame)

    assert len(got) == len(expected)
    for mine, theirs in zip(got, expected, strict=True):
        assert list(mine) == list(theirs)
        for key, value in theirs.items():
            assert type(mine[key]) is type(value), key
            assert mine[key] == value or (pd.isna(value) and pd.isna(mine[key])), key


def test_an_empty_frame_has_no_records() -> None:
    assert records(_frame().iloc[0:0]) == []
