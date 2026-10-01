import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Every other /api/v1 route must answer 401 without a session.
PUBLIC_ROUTES = {
    ("GET", "/api/v1/health"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
}


def _api_routes(app: FastAPI) -> set[tuple[str, str]]:
    # Listed from the schema: FastAPI nests included routers, so `app.routes` does not
    # flatten them. A route hidden with include_in_schema=False would escape this check.
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/v1")
        for method in operations
    }


def test_public_routes_exist(app: FastAPI) -> None:
    # A renamed public route would otherwise slip out of the allowlist unnoticed.
    assert PUBLIC_ROUTES <= _api_routes(app)


def test_every_other_api_route_requires_a_session(app: FastAPI, client: TestClient) -> None:
    protected = sorted(_api_routes(app) - PUBLIC_ROUTES)
    assert protected, "expected at least one protected route"
    for method, path in protected:
        url = re.sub(r"\{[^}]+\}", "1", path)
        response = client.request(method, url)
        assert response.status_code == 401, f"{method} {path} is reachable without a session"
