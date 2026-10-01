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
    assert Settings(_env_file=None).static_dir is None


@pytest.mark.parametrize("path", ["/api", "/api/"])
def test_bare_api_prefix_is_404_not_index(static_client: TestClient, path: str) -> None:
    response = static_client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_client_route_that_only_starts_with_api_gets_index(static_client: TestClient) -> None:
    # Only the /api segment is reserved; a client route like /apiary is still the SPA's.
    response = static_client.get("/apiary")
    assert response.status_code == 200
    assert '<div id="root">' in response.text


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_unknown_api_path_is_404_for_every_method(static_client: TestClient, method: str) -> None:
    # Same answer as without the SPA mounted: a typo'd API call is "not found",
    # not "method not allowed" because the SPA catch-all happens to match the path.
    response = static_client.request(method, "/api/v1/nope")
    assert response.status_code == 404


def test_encoded_traversal_falls_back_to_index(static_client: TestClient) -> None:
    response = static_client.get("/..%2Fsecret.txt")
    assert response.status_code == 200
    assert '<div id="root">' in response.text


def test_sibling_directory_sharing_the_prefix_is_not_served(
    settings: Settings, tmp_path: Path
) -> None:
    # /x/static-private starts with the string "/x/static" but is not inside it.
    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text(INDEX_HTML)
    (tmp_path / "static-private").mkdir()
    (tmp_path / "static-private" / "key.txt").write_text("private-key")
    app = create_app(settings=settings.model_copy(update={"static_dir": static_dir}))

    with TestClient(app) as client:
        response = client.get("/..%2Fstatic-private%2Fkey.txt")

    assert "private-key" not in response.text


def test_symlink_pointing_outside_static_dir_is_not_served(
    settings: Settings, tmp_path: Path
) -> None:
    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text(INDEX_HTML)
    (tmp_path / "outside.txt").write_text("outside-data")
    (static_dir / "link.txt").symlink_to(tmp_path / "outside.txt")
    app = create_app(settings=settings.model_copy(update={"static_dir": static_dir}))

    with TestClient(app) as client:
        response = client.get("/link.txt")

    assert "outside-data" not in response.text
    assert '<div id="root">' in response.text


def test_spa_mount_does_not_change_the_openapi_schema(settings: Settings, tmp_path: Path) -> None:
    # The CI drift check exports the schema; it must not depend on STATIC_DIR.
    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text(INDEX_HTML)

    without_spa = create_app(settings=settings).openapi()
    with_spa = create_app(settings=settings.model_copy(update={"static_dir": static_dir})).openapi()

    assert with_spa == without_spa


def test_static_dir_without_index_html_fails_at_startup(settings: Settings, tmp_path: Path) -> None:
    # A missing assets/ already fails at startup; a missing index.html should too,
    # instead of booting and answering every page with a 500.
    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)

    with pytest.raises(RuntimeError):
        create_app(settings=settings.model_copy(update={"static_dir": static_dir}))


def test_non_get_to_a_client_route_is_404(static_client: TestClient) -> None:
    # Same as without the SPA: only GET/HEAD fall back to index.html.
    assert static_client.post("/c/AAPL").status_code == 404


def test_head_on_a_client_route_returns_index_headers(static_client: TestClient) -> None:
    response = static_client.head("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_wrong_method_on_a_real_api_route_is_still_405(static_client: TestClient) -> None:
    assert static_client.post("/api/v1/health").status_code == 405
