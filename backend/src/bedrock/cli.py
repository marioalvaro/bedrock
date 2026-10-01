import json

import typer
from argon2 import PasswordHasher

from bedrock.core.config import Settings
from bedrock.main import create_app

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
