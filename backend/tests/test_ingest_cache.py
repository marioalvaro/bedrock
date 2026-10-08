from datetime import date
from pathlib import Path

from bedrock.ingest.cache import RawCache


def test_write_stores_the_body_under_the_cik_and_day(tmp_path: Path) -> None:
    path = RawCache(tmp_path).write("0000320193", date(2026, 10, 8), b'{"a": 1}')

    assert path == tmp_path / "raw" / "edgar" / "0000320193" / "2026-10-08.json"
    assert path.read_bytes() == b'{"a": 1}'


def test_writing_twice_on_one_day_replaces_the_file(tmp_path: Path) -> None:
    cache = RawCache(tmp_path)
    cache.write("0000320193", date(2026, 10, 8), b"one")

    path = cache.write("0000320193", date(2026, 10, 8), b"two")

    assert path.read_bytes() == b"two"
