import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from bedrock.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_root_env_file_overrides_backend_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The root .env is canonical (Compose reads it); a stale backend/.env must not win.
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / ".env").write_text("SESSION_IDLE_MINUTES=5\n")
    (tmp_path / ".env").write_text("SESSION_IDLE_MINUTES=30\n")
    monkeypatch.delenv("SESSION_IDLE_MINUTES", raising=False)
    monkeypatch.chdir(backend)

    assert Settings(session_secret="test-secret").session_idle_minutes == 30


def _documented_keys() -> set[str]:
    text = (REPO_ROOT / ".env.example").read_text()
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE))


def test_env_example_documents_every_setting() -> None:
    settings_keys = {name.upper() for name in Settings.model_fields}
    assert settings_keys - _documented_keys() == set()


def test_env_example_has_no_keys_the_backend_ignores() -> None:
    # Settings uses extra="ignore", so a typo'd key would be silently dropped.
    settings_keys = {name.upper() for name in Settings.model_fields}
    assert _documented_keys() - settings_keys == set()


@pytest.mark.parametrize("var", ["SEC_USER_AGENT", "FRED_API_KEY"])
def test_blank_optional_setting_means_unset(monkeypatch: pytest.MonkeyPatch, var: str) -> None:
    # .env.example ships these as `KEY=`; a blank must read as "not configured" (G9).
    monkeypatch.setenv(var, "")
    settings = Settings(_env_file=None, session_secret="test-secret")
    assert getattr(settings, var.lower()) is None


def test_blank_database_url_falls_back_to_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    settings = Settings(_env_file=None, data_dir=tmp_path, session_secret="test-secret")
    assert settings.resolved_database_url == f"sqlite:///{tmp_path}/bedrock.db"


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_session_secret_is_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    # `cp .env.example .env` without filling SESSION_SECRET must not sign cookies with "" (G10).
    monkeypatch.setenv("SESSION_SECRET", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_missing_session_secret_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # A built-in default would be a published key, as forgeable as a blank one (G10).
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_test_settings_ignore_the_developers_environment(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    # A deploy-oriented value (HTTPS cookies for tailscale serve) in the developer's
    # environment or .env must not change what the suite tests.
    monkeypatch.setenv("COOKIE_SECURE", "true")
    client: TestClient = request.getfixturevalue("authed_client")
    assert client.get("/api/v1/auth/me").status_code == 200


HOSTILE_ENV = {
    "DATA_DIR": "/nonexistent-bedrock",
    "DATABASE_URL": "sqlite:////nonexistent-bedrock/bedrock.db",
    "SEC_USER_AGENT": "hostile-agent",
    "FRED_API_KEY": "hostile-key",
    "APP_PASSWORD_HASH": "hostile-hash",
    "SESSION_SECRET": "hostile-secret",
    "SESSION_IDLE_MINUTES": "0",
    "COOKIE_SECURE": "true",
    "STATIC_DIR": "/nonexistent-bedrock-static",
}


def test_test_settings_pin_every_field_against_the_environment(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    # A new setting must be pinned in conftest's `settings`, or this suite starts
    # depending on whatever the developer has in their env or .env (G11).
    for name in Settings.model_fields:
        assert name.upper() in HOSTILE_ENV, f"add a hostile value for {name.upper()}"
        monkeypatch.setenv(name.upper(), HOSTILE_ENV[name.upper()])
    from_env = Settings(_env_file=None)

    settings: Settings = request.getfixturevalue("settings")
    leaked = [n for n in Settings.model_fields if getattr(settings, n) == getattr(from_env, n)]
    assert leaked == []

    client: TestClient = request.getfixturevalue("authed_client")
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.get("/api/v1/companies").status_code == 200
