import json

import typer
from argon2 import PasswordHasher

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
    schema = create_app().openapi()
    with open(path, "w") as f:
        json.dump(schema, f, indent=2, sort_keys=True)
        f.write("\n")
