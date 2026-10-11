import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

import typer
from argon2 import PasswordHasher
from sqlalchemy.orm import Session

from bedrock.core.config import Settings, load_settings
from bedrock.core.db import make_engine, make_sessionmaker
from bedrock.ingest.sources import Sources, build_sources
from bedrock.main import create_app
from bedrock.repositories import companies as companies_repo
from bedrock.services import companies as companies_service
from bedrock.services.errors import DOMAIN_ERRORS, user_message
from bedrock.services.mappings import sync_mappings
from bedrock.services.refresh import RefreshResult, refresh_company

app = typer.Typer()


@app.command("hash-password")
def hash_password() -> None:
    password = typer.prompt("Password", hide_input=True)
    confirm = typer.prompt("Confirm password", hide_input=True)
    if password != confirm:
        typer.echo("Passwords do not match", err=True)
        raise typer.Exit(code=1)

    hasher = PasswordHasher()
    typer.echo(hasher.hash(password))


@app.command("export-openapi")
def export_openapi(path: str) -> None:
    # Building the schema never signs a cookie, so it needs no real SESSION_SECRET
    # (CI runs this with no .env).
    schema = create_app(Settings(session_secret="unused-by-schema-export")).openapi()
    with open(path, "w") as f:
        json.dump(schema, f, indent=2, sort_keys=True)
        f.write("\n")


def _run(tickers: list[str], action: Callable[[Session, Sources, str], list[str]]) -> None:
    """Run `action` for each ticker on one session, printing the lines it returns or the reason
    it failed. Every ticker is tried; the exit code is 1 if any failed."""
    settings = load_settings()
    sources = build_sources(settings)
    engine = make_engine(settings.resolved_database_url)
    failed = False
    try:
        with make_sessionmaker(engine)() as session:
            for ticker in tickers:
                try:
                    for line in action(session, sources, ticker):
                        typer.echo(line)
                except DOMAIN_ERRORS as error:
                    failed = True
                    typer.echo(f"{ticker.upper()}: error: {user_message(error)}", err=True)
    finally:
        engine.dispose()
    if failed:
        raise typer.Exit(code=1)


def _result_lines(result: RefreshResult) -> list[str]:
    return [
        result.ticker,
        f"  new_filings: {result.new_filings}",
        f"  new_facts: {result.new_facts}",
        f"  new_prices: {result.new_prices}",
        f"  last_refreshed_at: {result.last_refreshed_at.isoformat()}",
        *(f"  warning: {warning}" for warning in result.warnings),
    ]


@app.command("add")
def add(tickers: list[str]) -> None:
    """Follow companies by ticker and load their data."""

    def follow(session: Session, sources: Sources, ticker: str) -> list[str]:
        view = companies_service.add_company(session, sources, ticker, datetime.now(UTC))
        return [f"{view.company.ticker}: added {view.company.name}"]

    _run(tickers, follow)


@app.command("refresh")
def refresh(
    tickers: Annotated[list[str] | None, typer.Argument()] = None,
    all_companies: Annotated[bool, typer.Option("--all", help="Every followed company")] = False,
) -> None:
    """Load new filings and prices for companies already followed."""
    if all_companies == bool(tickers):
        typer.echo("Give tickers, or --all (not both).", err=True)
        raise typer.Exit(code=2)
    if all_companies:
        engine = make_engine(load_settings().resolved_database_url)
        with make_sessionmaker(engine)() as session:
            tickers = [c.ticker for c in companies_repo.list_all(session)]
        engine.dispose()

    def run(session: Session, sources: Sources, ticker: str) -> list[str]:
        return _result_lines(refresh_company(session, sources, ticker, datetime.now(UTC)))

    _run(tickers or [], run)


@app.command("sync-mappings")
def sync_mappings_command() -> None:
    """Load canonical_items.yaml and the overrides into the database."""
    engine = make_engine(load_settings().resolved_database_url)
    try:
        with make_sessionmaker(engine)() as session:
            sync_mappings(session)
            session.commit()
    finally:
        engine.dispose()
    typer.echo("Mappings synced.")
