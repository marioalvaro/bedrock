from datetime import date
from pathlib import Path


class RawCache:
    """The raw EDGAR JSON as fetched, kept on disk (it survives removing a company)."""

    def __init__(self, data_dir: Path) -> None:
        self._root = data_dir / "raw" / "edgar"

    def write(self, cik: str, day: date, body: bytes) -> Path:
        path = self._root / cik / f"{day.isoformat()}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return path
