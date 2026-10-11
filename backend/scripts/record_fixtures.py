"""Record the offline test fixtures from the real sources (needs network and SEC_USER_AGENT).

Usage (from backend/):  uv run python scripts/record_fixtures.py AAPL MSFT COST

Writes, under tests/fixtures/:
  edgar/<TICKER>.json.gz              full companyfacts (gzipped; no timestamp, so re-recording
                                      an unchanged payload gives an identical file)
  edgar/submissions/<TICKER>.json     trimmed to cik, name, sic, fiscalYearEnd, tickers
  edgar/company_tickers.json          the entries of the recorded tickers (merged across runs)
  yfinance/<TICKER>.csv               the last year of daily prices
"""

import gzip
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import yfinance as yf

from bedrock.core.config import load_settings
from bedrock.ingest.cache import RawCache
from bedrock.ingest.http import RateLimitedClient
from bedrock.ingest.protocol import CompanyRef, SourceNotConfigured
from bedrock.ingest.sources.edgar import EdgarSource

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
SUBMISSION_KEYS = ("cik", "name", "sic", "fiscalYearEnd", "tickers")


def _write_json(path: Path, doc: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")


def record_edgar(client: RateLimitedClient, edgar: EdgarSource, tickers: list[str]) -> None:
    all_tickers = client.get_json("https://www.sec.gov/files/company_tickers.json")
    tickers_path = FIXTURES / "edgar" / "company_tickers.json"
    kept: dict[str, dict[str, object]] = (
        json.loads(tickers_path.read_text()) if tickers_path.exists() else {}
    )
    for ticker in tickers:
        profile = edgar.resolve(ticker)
        entry = next(v for v in all_tickers.values() if v["ticker"] == profile.ticker)
        kept[str(entry["cik_str"])] = entry

        submissions = client.get_json(f"https://data.sec.gov/submissions/CIK{profile.cik}.json")
        _write_json(
            FIXTURES / "edgar" / "submissions" / f"{ticker}.json",
            {key: submissions[key] for key in SUBMISSION_KEYS},
        )

        payload = edgar.fetch(CompanyRef(ticker, profile.cik), None)
        body = json.dumps(payload.companyfacts, separators=(",", ":"), sort_keys=True)
        path = FIXTURES / "edgar" / f"{ticker}.json.gz"
        path.write_bytes(gzip.compress(body.encode(), mtime=0))
        print(f"{ticker}: {path.relative_to(FIXTURES.parent)} ({path.stat().st_size // 1024} KiB)")
    _write_json(tickers_path, kept)


def record_prices(tickers: list[str]) -> None:
    start = date.today() - timedelta(days=365)
    for ticker in tickers:
        frame = yf.Ticker(ticker).history(start=start, auto_adjust=False, actions=False)
        frame.index = [stamp.date().isoformat() for stamp in frame.index]
        frame.index.name = "Date"
        path = FIXTURES / "yfinance" / f"{ticker}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path)
        print(f"{ticker}: {path.relative_to(FIXTURES.parent)} ({len(frame)} rows)")


def main(tickers: list[str]) -> int:
    if not tickers:
        print(__doc__)
        return 2
    settings = load_settings()
    if not settings.sec_user_agent:
        raise SourceNotConfigured("SEC_USER_AGENT is not set")
    client = RateLimitedClient(settings.sec_user_agent)
    edgar = EdgarSource(lambda: client, RawCache(settings.data_dir))
    tickers = [t.upper() for t in tickers]
    record_edgar(client, edgar, tickers)
    record_prices(tickers)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
