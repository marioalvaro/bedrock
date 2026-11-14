"""One filing's XBRL files from the EDGAR archive (docs/erd/data-coverage.md "Files per filing").

The folder's `index.json` lists its files; the instance, the schema and the linkbases are chosen
by name pattern, never by a hardcoded name. Every file fetched (the index too) is kept gzipped
under `DATA_DIR/raw/edgar/<cik10>/filings/<accession>/` and never fetched again."""

import gzip
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from bedrock.ingest.http import RateLimitedClient
from bedrock.ingest.protocol import CompanyRef, SourceUnavailable

_FOLDER_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"
_INDEX = "index.json"
_LINKBASE = re.compile(r".+_(pre|cal|lab)\.xml$", re.IGNORECASE)
_NOT_INSTANCE = re.compile(r".+_(pre|cal|lab|def|ref)\.xml$", re.IGNORECASE)


def select_files(names: list[str]) -> list[str]:
    """The files the parser needs, or [] when the folder has no instance.

    The instance is the inline-XBRL extract (`*_htm.xml`), else, for a filing before inline XBRL,
    the `.xml` named like the schema. Linkbases may also sit inside the schema (e.g. MSFT 2024),
    so a missing `_pre`/`_cal`/`_lab` file is not an error."""
    schemas = [n for n in names if n.lower().endswith(".xsd")]
    instance = next((n for n in names if n.lower().endswith("_htm.xml")), None)
    if instance is None:
        stems = {n[: -len(".xsd")].lower() for n in schemas}
        instance = next(
            (
                n
                for n in names
                if n.lower().endswith(".xml")
                and not _NOT_INSTANCE.match(n)
                and n[: -len(".xml")].lower() in stems
            ),
            None,
        )
    if instance is None:
        return []
    return sorted({instance, *schemas, *(n for n in names if _LINKBASE.match(n))})


class EdgarFilingsSource:
    name: ClassVar[str] = "edgar_filings"

    def __init__(self, client_factory: Callable[[], RateLimitedClient], data_dir: Path) -> None:
        self._client_factory = client_factory
        self._root = data_dir / "raw" / "edgar"
        self._client: RateLimitedClient | None = None

    def fetch(self, company: CompanyRef, accession_no: str) -> dict[str, bytes]:
        """The filing's XBRL files by name; {} when the folder has no XBRL instance. Raises
        SourceUnavailable on a network or HTTP failure (what was fetched stays cached)."""
        if company.cik is None:
            raise ValueError(f"{company.ticker} has no CIK: EDGAR holds nothing for it")
        folder_url = _FOLDER_URL.format(
            cik=int(company.cik), accession=accession_no.replace("-", "")
        )
        cache = self._root / company.cik / "filings" / accession_no
        listing = self._file(cache, folder_url, _INDEX)
        try:
            names = [item["name"] for item in json.loads(listing)["directory"]["item"]]
        except (ValueError, KeyError, TypeError) as error:
            raise SourceUnavailable(f"{folder_url}{_INDEX}: not a folder listing") from error
        return {name: self._file(cache, folder_url, name) for name in select_files(names)}

    def _file(self, cache: Path, folder_url: str, name: str) -> bytes:
        path = cache / f"{name}.gz"
        if path.is_file():
            try:
                return gzip.decompress(path.read_bytes())
            except (OSError, EOFError):  # a corrupt cached file is a miss: fetched again
                path.unlink()
        body = self._get_client().get(folder_url + name)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written to a temporary name first, so an interrupted write never looks cached.
        partial = path.with_suffix(".part")
        partial.write_bytes(gzip.compress(body, mtime=0))
        partial.replace(path)
        return body

    def _get_client(self) -> RateLimitedClient:
        # Built on first use, so a missing SEC_USER_AGENT fails there and never at app start.
        if self._client is None:
            self._client = self._client_factory()
        return self._client
