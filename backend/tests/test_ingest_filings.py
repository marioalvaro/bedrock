"""EdgarFilingsSource: one filing's XBRL files, discovered through `index.json` and cached on disk
(docs/erd/data-coverage.md "Files per filing"). Served by a fake HTTP transport: no network."""

import gzip
import json
from pathlib import Path

import httpx
import pytest

from bedrock.core.config import Settings
from bedrock.ingest.http import RateLimitedClient
from bedrock.ingest.protocol import CompanyRef, SourceUnavailable
from bedrock.ingest.sources import build_sources
from bedrock.ingest.sources.edgar_filings import EdgarFilingsSource

AAPL = CompanyRef("AAPL", "0000320193")
ACCESSION = "0000320193-24-000123"
FOLDER = "/Archives/edgar/data/320193/000032019324000123/"

# The file names SEC lists for each layout (recorded 2026-11-14, trimmed).
INLINE = [
    "0000320193-24-000123.txt",
    "0000320193-24-000123-xbrl.zip",
    "a10-kexhibit31109282024.htm",
    "aapl-20240928.htm",
    "aapl-20240928.xsd",
    "aapl-20240928_cal.xml",
    "aapl-20240928_def.xml",
    "aapl-20240928_htm.xml",
    "aapl-20240928_lab.xml",
    "aapl-20240928_pre.xml",
    "FilingSummary.xml",
    "MetaLinks.json",
    "R1.htm",
]
PRE_INLINE = [
    "aapl-20100925.xml",
    "aapl-20100925.xsd",
    "aapl-20100925_cal.xml",
    "aapl-20100925_def.xml",
    "aapl-20100925_lab.xml",
    "aapl-20100925_pre.xml",
    "d10k.htm",
    "defnref.xml",
    "FilingSummary.xml",
    "R1.xml",
    "R12.xml",
]
EMBEDDED_LINKBASES = ["msft-20240630.htm", "msft-20240630.xsd", "msft-20240630_htm.xml"]
INSTANCE_STEM_DIFFERS = [
    "de-20231029.xsd",
    "de-20231029x10k.htm",
    "de-20231029x10k_htm.xml",
    "de-20231029_cal.xml",
    "de-20231029_lab.xml",
    "de-20231029_pre.xml",
]
NO_XBRL = ["0000320193-08-000001.txt", "d10k.htm", "ex21.htm"]


class Folder:
    """One EDGAR filing folder: `index.json` lists `names`, each file's body is its own name."""

    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        if not path.startswith(FOLDER):
            return httpx.Response(404)
        name = path.removeprefix(FOLDER)
        if name == "index.json":
            items = [{"name": n, "type": "text.gif", "size": "1"} for n in self.names]
            return httpx.Response(200, json={"directory": {"item": items, "name": FOLDER}})
        if name in self.names:
            return httpx.Response(200, content=name.encode())
        return httpx.Response(404)


def _source(data_dir: Path, folder: Folder) -> EdgarFilingsSource:
    transport = httpx.MockTransport(folder)
    return EdgarFilingsSource(
        lambda: RateLimitedClient("me@example.com", transport=transport), data_dir
    )


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (
            INLINE,
            [
                "aapl-20240928.xsd",
                "aapl-20240928_cal.xml",
                "aapl-20240928_htm.xml",
                "aapl-20240928_lab.xml",
                "aapl-20240928_pre.xml",
            ],
        ),
        (
            PRE_INLINE,
            [
                "aapl-20100925.xml",
                "aapl-20100925.xsd",
                "aapl-20100925_cal.xml",
                "aapl-20100925_lab.xml",
                "aapl-20100925_pre.xml",
            ],
        ),
        (EMBEDDED_LINKBASES, ["msft-20240630.xsd", "msft-20240630_htm.xml"]),
        (
            INSTANCE_STEM_DIFFERS,
            [
                "de-20231029.xsd",
                "de-20231029_cal.xml",
                "de-20231029_lab.xml",
                "de-20231029_pre.xml",
                "de-20231029x10k_htm.xml",
            ],
        ),
    ],
    ids=["inline", "pre-inline", "embedded-linkbases", "instance-stem-differs"],
)
def test_the_instance_schema_and_linkbases_are_found_from_the_index(
    tmp_path: Path, names: list[str], expected: list[str]
) -> None:
    files = _source(tmp_path, Folder(names)).fetch(AAPL, ACCESSION)

    assert sorted(files) == expected
    assert all(files[name] == name.encode() for name in expected)


def test_the_folder_is_addressed_by_the_cik_and_accession_without_zeros_or_dashes(
    tmp_path: Path,
) -> None:
    folder = Folder(EMBEDDED_LINKBASES)

    _source(tmp_path, folder).fetch(AAPL, ACCESSION)

    assert folder.requests[0] == FOLDER + "index.json"
    assert all(path.startswith(FOLDER) for path in folder.requests)


def test_a_folder_without_an_instance_gives_no_files(tmp_path: Path) -> None:
    assert _source(tmp_path, Folder(NO_XBRL)).fetch(AAPL, ACCESSION) == {}


def test_a_schema_without_an_instance_gives_no_files(tmp_path: Path) -> None:
    names = ["aapl-20240928.xsd", "aapl-20240928_pre.xml", "aapl-20240928.htm"]

    assert _source(tmp_path, Folder(names)).fetch(AAPL, ACCESSION) == {}


def test_files_are_cached_gzipped_and_a_cached_filing_makes_no_request(tmp_path: Path) -> None:
    first = _source(tmp_path, Folder(INLINE)).fetch(AAPL, ACCESSION)
    cached = tmp_path / "raw" / "edgar" / "0000320193" / "filings" / ACCESSION
    assert gzip.decompress((cached / "aapl-20240928_htm.xml.gz").read_bytes()) == (
        b"aapl-20240928_htm.xml"
    )

    again = Folder(INLINE)
    second = _source(tmp_path, again).fetch(AAPL, ACCESSION)

    assert second == first
    assert again.requests == []


def test_a_cached_folder_without_an_instance_makes_no_request(tmp_path: Path) -> None:
    _source(tmp_path, Folder(NO_XBRL)).fetch(AAPL, ACCESSION)
    again = Folder(NO_XBRL)

    assert _source(tmp_path, again).fetch(AAPL, ACCESSION) == {}
    assert again.requests == []


def test_a_missing_folder_is_source_unavailable(tmp_path: Path) -> None:
    other = CompanyRef("MSFT", "0000789019")

    with pytest.raises(SourceUnavailable):
        _source(tmp_path, Folder(INLINE)).fetch(other, ACCESSION)


def test_after_a_failed_file_fetch_the_next_run_fetches_only_what_is_missing(
    tmp_path: Path,
) -> None:
    folder = Folder(INLINE)

    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("_pre.xml"):
            return httpx.Response(404)
        return folder(request)

    transport = httpx.MockTransport(serve)
    source = EdgarFilingsSource(
        lambda: RateLimitedClient("me@example.com", transport=transport), tmp_path
    )
    with pytest.raises(SourceUnavailable):
        source.fetch(AAPL, ACCESSION)

    retry = Folder(INLINE)
    files = _source(tmp_path, retry).fetch(AAPL, ACCESSION)

    assert retry.requests == [FOLDER + "aapl-20240928_pre.xml"]
    assert len(files) == 5


def test_a_company_without_a_cik_has_no_filings(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no CIK"):
        _source(tmp_path, Folder(INLINE)).fetch(CompanyRef("PRIV", None), ACCESSION)


def test_the_app_sources_include_the_filings_source(tmp_path: Path) -> None:
    sources = build_sources(Settings(data_dir=tmp_path, sec_user_agent="me@example.com"))

    assert isinstance(sources.filings, EdgarFilingsSource)


def test_the_index_is_read_as_json(tmp_path: Path) -> None:
    folder = Folder(INLINE)
    _source(tmp_path, folder).fetch(AAPL, ACCESSION)
    cached = tmp_path / "raw" / "edgar" / "0000320193" / "filings" / ACCESSION / "index.json.gz"

    listing = json.loads(gzip.decompress(cached.read_bytes()))

    assert [item["name"] for item in listing["directory"]["item"]] == INLINE


def test_a_corrupt_cached_file_is_fetched_again(tmp_path: Path) -> None:
    _source(tmp_path, Folder(INLINE)).fetch(AAPL, ACCESSION)
    cached = tmp_path / "raw" / "edgar" / "0000320193" / "filings" / ACCESSION
    (cached / "aapl-20240928_pre.xml.gz").write_bytes(b"not gzip")
    again = Folder(INLINE)

    files = _source(tmp_path, again).fetch(AAPL, ACCESSION)

    assert again.requests == [FOLDER + "aapl-20240928_pre.xml"]
    assert files["aapl-20240928_pre.xml"] == b"aapl-20240928_pre.xml"
