"""What the API shows of a statement table. Pure."""

from dataclasses import replace

from bedrock.statements.build import Row, StatementTable


def trim_periods(table: StatementTable) -> StatementTable:
    """Remove the periods the API should not show, keeping every row and each per-period array
    aligned:
    - a period in which no row has a value, such as the early fiscal years that predate XBRL;
    - a balance-sheet period whose check has no difference, i.e. one missing a total. Its values
      are comparatives from other statements, not a balance sheet. A sheet that is complete but
      does not balance has a difference, so it stays and shows as a failure."""
    checks = None if table.balance_check is None else {c.period_key: c for c in table.balance_check}
    keep = [
        i
        for i, period in enumerate(table.periods)
        if any(row.values[i] is not None for row in table.rows)
        and (checks is None or checks[period.key].difference is not None)
    ]
    if len(keep) == len(table.periods):
        return table
    kept_keys = {table.periods[i].key for i in keep}
    return replace(
        table,
        periods=[table.periods[i] for i in keep],
        rows=[_pick(row, keep) for row in table.rows],
        balance_check=(
            None
            if table.balance_check is None
            else [c for c in table.balance_check if c.period_key in kept_keys]
        ),
    )


def _pick(row: Row, keep: list[int]) -> Row:
    return replace(
        row,
        values=[row.values[i] for i in keep],
        provenance=[row.provenance[i] for i in keep],
        yoy=[row.yoy[i] for i in keep],
        common_size=[row.common_size[i] for i in keep],
    )
