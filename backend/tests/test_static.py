from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bedrock.core.config import Settings
from bedrock.main import create_app

INDEX_HTML = '<!doctype html><html><body><div id="root"></div></body></html>'


@pytest.fixture
def static_client(settings: Settings, tmp_path: Path) -> Generator[TestClient, None, None]:
    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text(INDEX_HTML)
    (static_dir / "assets" / "app.js").write_text("console.log('bedrock');")
    (static_dir / "favicon.svg").write_text("<svg></svg>")
    (tmp_path / "secret.txt").write_text("secret")
    app = create_app(settings=settings.model_copy(update={"static_dir": static_dir}))
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("path", ["/", "/login", "/c/AAPL", "/c/AAPL/overview"])
def test_spa_paths_return_index_html(static_client: TestClient, path: str) -> None:
    response = static_client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<div id="root">' in response.text


def test_assets_are_served(static_client: TestClient) -> None:
    response = static_client.get("/assets/app.js")
    assert response.status_code == 200
    assert "bedrock" in response.text


def test_missing_asset_is_404_not_index(static_client: TestClient) -> None:
    response = static_client.get("/assets/missing.js")
    assert response.status_code == 404


def test_root_level_static_files_are_served(static_client: TestClient) -> None:
    response = static_client.get("/favicon.svg")
    assert response.status_code == 200
    assert response.text == "<svg></svg>"


def test_paths_outside_static_dir_are_not_served(static_client: TestClient) -> None:
    response = static_client.get("/%2e%2e/secret.txt")
    assert "secret" not in response.text


def test_api_routes_still_return_json(static_client: TestClient) -> None:
    response = static_client.get("/api/v1/health")
    assert response.json() == {"status": "ok"}


def test_unknown_api_path_is_404_not_index(static_client: TestClient) -> None:
    response = static_client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_without_static_dir_root_is_404(client: TestClient) -> None:
    assert client.get("/").status_code == 404


def test_empty_static_dir_env_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    # Docker cannot unset an inherited ENV, so the dev profile blanks STATIC_DIR instead.
    monkeypatch.setenv("STATIC_DIR", "")
    assert Settings().static_dir is None
