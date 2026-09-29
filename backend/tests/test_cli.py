import json
from pathlib import Path

from argon2 import PasswordHasher
from typer.testing import CliRunner

from bedrock.cli import app

runner = CliRunner()


def test_hash_password_output_verifies() -> None:
    result = runner.invoke(app, ["hash-password"], input="test-password\ntest-password\n")
    assert result.exit_code == 0
    hashed = result.stdout.strip().splitlines()[-1]

    PasswordHasher().verify(hashed, "test-password")


def test_export_openapi_writes_valid_json_with_companies_path(tmp_path: Path) -> None:
    out_path = tmp_path / "openapi.json"
    result = runner.invoke(app, ["export-openapi", str(out_path)])
    assert result.exit_code == 0

    schema = json.loads(out_path.read_text())
    assert "/api/v1/companies" in schema["paths"]
