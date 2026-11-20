"""Time stamps as stored: SQLite keeps no time zone, so every DateTime column holds naive UTC."""

from datetime import UTC, datetime


def naive_utc(moment: datetime) -> datetime:
    """`moment` in UTC without its time zone; a naive `moment` is taken as UTC already."""
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment
