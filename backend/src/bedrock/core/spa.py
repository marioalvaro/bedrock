from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException


def _is_reserved(path: str) -> bool:
    # API and hashed-bundle paths answer for themselves: a miss there is a real 404.
    return any(path == prefix or path.startswith(prefix + "/") for prefix in ("/api", "/assets"))


def mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve the built SPA: hashed bundles under /assets, and, as the 404 fallback for
    GET/HEAD outside /api and /assets, a real file at the root or else index.html, so
    client-side routes survive a reload. Every other request behaves as if no SPA
    were mounted.
    """
    root = static_dir.resolve()
    index = root / "index.html"
    # Fail at startup, like StaticFiles does for a missing assets/, rather than
    # booting and answering every page with a 500.
    if not index.is_file():
        raise RuntimeError(f"STATIC_DIR {root} has no index.html; was the frontend built?")

    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    async def spa_fallback(request: Request, exc: Exception) -> Response:
        if not isinstance(exc, HTTPException):  # status handlers only receive these
            raise exc
        path = request.url.path
        if request.method not in ("GET", "HEAD") or _is_reserved(path):
            return await http_exception_handler(request, exc)
        candidate = (root / path.lstrip("/")).resolve()
        if candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)

    # A status handler runs only after routing failed, so it never shadows an API
    # route or turns a 405 into a 404.
    app.add_exception_handler(404, spa_fallback)
