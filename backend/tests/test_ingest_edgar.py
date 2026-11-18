import gzip
import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from bedrock.core.config import Settings
from bedrock.ingest.cache import RawCache
from bedrock.ingest.http import RateLimitedClient
from bedrock.ingest.protocol import (
    CompanyRef,
    SourceNotConfigured,
    SourceUnavailable,
    UnknownTicker,
)
from bedrock.ingest.sources import build_sources
from bedrock.ingest.sources.edgar import EdgarSource

EDGAR = Path(__file__).parent / "fixtures" / "edgar"
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def _serve(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/files/company_tickers.json":
        return httpx.Response(200, content=(EDGAR / "company_tickers.json").read_bytes())
    if path.startswith("/submissions/CIK"):
        cik = path.removeprefix("/submissions/CIK").removesuffix(".json")
        for file in (EDGAR / "submissions").glob("*.json"):
            if json.loads(file.read_text())["cik"] == cik:
                return httpx.Response(200, content=file.read_bytes())
    if path.startswith("/api/xbrl/companyfacts/CIK"):
        cik = path.removeprefix("/api/xbrl/companyfacts/CIK").removesuffix(".json")
        for file in EDGAR.glob("*.json.gz"):
            raw = gzip.decompress(file.read_bytes())
            if int(json.loads(raw)["cik"]) == int(cik):
                return httpx.Response(200, content=raw)
    return httpx.Response(404)


def _source(tmp_path: Path, handler: object = _serve) -> EdgarSource:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return EdgarSource(
        lambda: RateLimitedClient("me@example.com", transport=transport),
        RawCache(tmp_path),
        clock=lambda: NOW,
    )


def test_resolving_aapl_gives_its_cik_and_fiscal_year_end_month(tmp_path: Path) -> None:
    profile = _source(tmp_path).resolve("AAPL")

    assert profile.cik == "0000320193"
    assert profile.ticker == "AAPL"
    assert profile.name == "Apple Inc."
    assert profile.sic == "3571"
    assert profile.fiscal_year_end_month == 9


def test_resolving_is_case_insensitive_and_reads_other_fiscal_year_ends(tmp_path: Path) -> None:
    source = _source(tmp_path)

    assert source.resolve("msft").fiscal_year_end_month == 6
    assert source.resolve("COST").fiscal_year_end_month == 8


def test_an_unknown_ticker_raises(tmp_path: Path) -> None:
    with pytest.raises(UnknownTicker):
        _source(tmp_path).resolve("NOPE")


def test_without_a_user_agent_the_first_call_raises_source_not_configured(
    settings: Settings, tmp_path: Path
) -> None:
    sources = build_sources(settings)  # building makes no call and does not raise

    with pytest.raises(SourceNotConfigured):
        sources.edgar.resolve("AAPL")
    with pytest.raises(SourceNotConfigured):
        sources.edgar.fetch(CompanyRef("AAPL", "0000320193"), None)


def test_fetch_returns_companyfacts_and_writes_the_cache(tmp_path: Path) -> None:
    payload = _source(tmp_path).fetch(CompanyRef("AAPL", "0000320193"), None)

    assert "us-gaap" in payload.companyfacts["facts"]
    assert payload.fetched_at == NOW
    cached = tmp_path / "raw" / "edgar" / "0000320193" / "2026-10-08.json"
    assert json.loads(cached.read_bytes()) == payload.companyfacts


def test_fetch_refuses_a_company_without_a_cik(tmp_path: Path) -> None:
    # A manual company has no SEC filer; the refresh never asks EDGAR for it.
    with pytest.raises(ValueError, match="CIK"):
        _source(tmp_path).fetch(CompanyRef("ACME", None), None)


def test_fetch_ignores_since_and_always_returns_the_full_history(tmp_path: Path) -> None:
    ref = CompanyRef("AAPL", "0000320193")
    source = _source(tmp_path)

    assert source.fetch(ref, date(2026, 1, 1)).companyfacts == source.fetch(ref, None).companyfacts


def test_an_upstream_failure_is_source_unavailable(tmp_path: Path) -> None:
    source = _source(tmp_path, lambda request: httpx.Response(404))

    with pytest.raises(SourceUnavailable):
        source.fetch(CompanyRef("AAPL", "0000320193"), None)


def test_the_client_is_built_once_and_only_on_first_use(tmp_path: Path) -> None:
    built: list[int] = []
    transport = httpx.MockTransport(_serve)

    def factory() -> RateLimitedClient:
        built.append(1)
        return RateLimitedClient("me@example.com", transport=transport)

    source = EdgarSource(factory, RawCache(tmp_path), clock=lambda: NOW)
    assert built == []

    source.resolve("AAPL")
    source.resolve("MSFT")
    assert built == [1]


# --- the filing index (M7c, FR-DATA-23) ---------------------------------------------------------


def _serve_index(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/submissions/CIK0000320193.json":
        return httpx.Response(200, content=(EDGAR / "recent_filings" / "AAPL.json").read_bytes())
    return httpx.Response(404)


def test_recent_filings_reads_the_10_k_and_10_q_rows_of_the_index(tmp_path: Path) -> None:
    refs = _source(tmp_path, _serve_index).recent_filings(CompanyRef("AAPL", "0000320193"))

    assert [(r.accession_no, r.form) for r in refs] == [
        ("0000320193-26-000029", "10-K"),
        ("0000320193-26-000020", "10-Q"),
        ("0000320193-26-000013", "10-Q"),
    ]
    assert not (tmp_path / "raw").exists()  # the index is never cached on disk


def test_recent_filings_refuses_a_company_without_a_cik(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="CIK"):
        _source(tmp_path, _serve_index).recent_filings(CompanyRef("ACME", None))


def test_an_index_failure_is_source_unavailable(tmp_path: Path) -> None:
    source = _source(tmp_path, lambda request: httpx.Response(503))

    with pytest.raises(SourceUnavailable):
        source.recent_filings(CompanyRef("AAPL", "0000320193"))


def test_build_sources_reads_the_index_with_the_edgar_source(settings: Settings) -> None:
    sources = build_sources(settings)

    assert sources.submissions is sources.edgar


@pytest.mark.parametrize(
    "body",
    [
        {"filings": {"recent": {"accessionNumber": ["a1"], "form": ["10-Q"]}}},  # a column missing
        {
            "filings": {
                "recent": {
                    "accessionNumber": ["a1"],
                    "form": ["10-Q"],
                    "filingDate": ["31/07/2026"],
                    "reportDate": [""],
                }
            }
        },  # bad date
        {
            "filings": {
                "recent": {
                    "accessionNumber": ["a1", "a2"],
                    "form": ["10-Q"],
                    "filingDate": ["2026-07-31"],
                    "reportDate": [""],
                }
            }
        },  # uneven
        {"filings": {"recent": ["not", "a", "table"]}},
        ["not", "a", "document"],
    ],
)
def test_an_index_of_an_unexpected_shape_is_source_unavailable(
    tmp_path: Path, body: object
) -> None:
    source = _source(tmp_path, lambda request: httpx.Response(200, json=body))

    with pytest.raises(SourceUnavailable, match="unexpected"):
        source.recent_filings(CompanyRef("AAPL", "0000320193"))
