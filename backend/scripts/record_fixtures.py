"""Record the offline test fixtures from the real sources (needs network and SEC_USER_AGENT).

Usage (from backend/):  uv run python scripts/record_fixtures.py [--only KIND]... AAPL MSFT COST
  --only edgar|prices|splits|filings   record just that kind (repeatable; default: the first
                                       three; `filings` only when asked for).
  Only `edgar` needs SEC_USER_AGENT. Re-recording an old ticker's edgar or prices moves its
  goldens, so add a ticker with all kinds and refresh an old one with `--only splits`.

Writes, under tests/fixtures/:
  edgar/<TICKER>.json.gz              full companyfacts (gzipped; no timestamp, so re-recording
                                      an unchanged payload gives an identical file)
  edgar/submissions/<TICKER>.json     trimmed to cik, name, sic, fiscalYearEnd, tickers
  edgar/company_tickers.json          the entries of the recorded tickers (merged across runs)
  yfinance/<TICKER>.csv               the last year of daily prices
  yfinance/<TICKER>_splits.csv        the full split history (`date,ratio`, oldest first;
                                      header only for a company that never split)
  edgar/filings/<TICKER>/<accession>/<name>.gz
                                      the XBRL files of the filings in `FILINGS` (M7b S6), as
                                      `EdgarFilingsSource` selects them, each gzipped
"""

import argparse
import gzip
import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import yfinance as yf

from bedrock.core.config import load_settings
from bedrock.ingest.cache import RawCache
from bedrock.ingest.http import RateLimitedClient
from bedrock.ingest.protocol import CompanyRef, SourceNotConfigured
from bedrock.ingest.sources.edgar import EdgarSource
from bedrock.ingest.sources.edgar_filings import EdgarFilingsSource

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
SUBMISSION_KEYS = ("cik", "name", "sic", "fiscalYearEnd", "tickers")


def _write_json(path: Path, doc: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")


def record_edgar(tickers: list[str]) -> None:
    settings = load_settings()
    if not settings.sec_user_agent:
        raise SourceNotConfigured("SEC_USER_AGENT is not set")
    client = RateLimitedClient(settings.sec_user_agent)
    edgar = EdgarSource(lambda: client, RawCache(settings.data_dir))
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


def format_ratio(ratio: float) -> str:
    """`7.0` -> `7`, `0.1` -> `0.1`, `20.0` -> `20` (never scientific notation)."""
    return f"{Decimal(str(ratio)).normalize():f}"


def record_splits(tickers: list[str]) -> None:
    for ticker in tickers:
        splits = yf.Ticker(ticker).splits
        path = FIXTURES / "yfinance" / f"{ticker}_splits.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["date,ratio"]
        for stamp, ratio in splits.sort_index().items():
            if float(ratio) != 0:
                lines.append(f"{stamp.date().isoformat()},{format_ratio(float(ratio))}")
        path.write_text("\n".join(lines) + "\n")
        print(f"{ticker}: {path.relative_to(FIXTURES.parent)} ({len(lines) - 1} splits)")


# One filing per layout the XBRL parser must read (M7b S6), then (M7b S7) the newest 10-K and
# 10-Q of each development company in its companyfacts fixture, whose face lines the structure
# rules and the triage guard read, and Deere's FY2019 and FY2021
# 10-Ks (the `de:` lines of its extension-tag years).
FILINGS = {
    "AAPL": [
        "0000320193-24-000123",  # 10-K FY2024
        "0001193125-10-238044",  # 10-K FY2010
        "0000320193-25-000079",  # 10-K FY2025
        "0000320193-26-000020",  # 10-Q Q3 FY2026
    ],
    "MSFT": [
        "0000950170-24-087843",  # 10-K FY2024
        "0001193125-15-272806",  # 10-K FY2015
        "0001193125-26-323660",  # 10-K FY2026
        "0001193125-26-191507",  # 10-Q Q3 FY2026
    ],
    "DE": [
        "0001558370-23-019812",  # 10-K FY2023
        "0001104659-25-122321",  # 10-K FY2025
        "0001104659-26-102213",  # 10-Q Q3 FY2026
        "0001558370-19-011614",  # 10-K FY2019
        "0001558370-21-016864",  # 10-K FY2021
    ],
    "COST": [
        "0000909832-24-000017",  # 10-Q Q2 FY2024
        "0000909832-26-000093",  # 10-K FY2026
        "0000909832-26-000051",  # 10-Q Q3 FY2026
    ],
    "BA": ["0001628280-26-004357", "0001628280-26-067508"],  # 10-K FY2025; 10-Q Q3 FY2026
    "JNJ": ["0000200406-26-000016", "0000200406-26-000197"],  # 10-K FY2025; 10-Q Q3 FY2026
    "NFLX": ["0001065280-26-000034", "0001065280-26-000291"],  # 10-K FY2025; 10-Q Q3 FY2026
    "NKE": ["0000320187-26-000088", "0000320187-26-000193"],  # 10-K FY2026; 10-Q Q1 FY2027
    "ORCL": ["0001193125-26-277521", "0001193125-26-389274"],  # 10-K FY2026; 10-Q Q1 FY2027
    "WMT": ["0000104169-26-000055", "0000104169-26-000154"],  # 10-K FY2026; 10-Q Q2 FY2027
}


def record_filings(tickers: list[str]) -> None:
    settings = load_settings()
    if not settings.sec_user_agent:
        raise SourceNotConfigured("SEC_USER_AGENT is not set")
    client = RateLimitedClient(settings.sec_user_agent)
    filings = EdgarFilingsSource(lambda: client, settings.data_dir)
    edgar = EdgarSource(lambda: client, RawCache(settings.data_dir))
    for ticker in tickers:
        profile = edgar.resolve(ticker)
        for accession in FILINGS.get(ticker, []):
            files = filings.fetch(CompanyRef(ticker, profile.cik), accession)
            folder = FIXTURES / "edgar" / "filings" / ticker / accession
            folder.mkdir(parents=True, exist_ok=True)
            for name, body in files.items():
                (folder / f"{name}.gz").write_bytes(gzip.compress(body, mtime=0))
            size = sum(p.stat().st_size for p in folder.iterdir()) // 1024
            print(f"{ticker} {accession}: {len(files)} files ({size} KiB)")


KINDS = ("edgar", "prices", "splits", "filings")
DEFAULT_KINDS = ("edgar", "prices", "splits")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="record_fixtures.py", add_help=True)
    parser.add_argument("--only", action="append", choices=KINDS, default=None)
    parser.add_argument("tickers", nargs="*")
    args = parser.parse_args(argv)
    if not args.tickers:
        print(__doc__)
        return 2
    tickers = [t.upper() for t in args.tickers]
    wanted = set(args.only or DEFAULT_KINDS)
    # Looked up by name at call time, so a test can replace the recorders.
    for kind in KINDS:
        if kind in wanted:
            globals()[f"record_{kind}"](tickers)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
