from datetime import date

from bedrock.models.filing import Filing


def test_the_read_before_a_filing_is_as_of_the_day_before_it_was_filed() -> None:
    filing = Filing(form="10-Q", filed_at=date(2026, 5, 1), period_end=date(2026, 3, 28))
    assert filing.before_as_of == date(2026, 4, 30)


def test_the_day_before_crosses_a_year_boundary() -> None:
    filing = Filing(form="10-K", filed_at=date(2026, 1, 1), period_end=date(2025, 9, 27))
    assert filing.before_as_of == date(2025, 12, 31)
