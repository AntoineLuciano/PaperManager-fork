"""Auth guards on library-wide routers, and nginx coverage of every API prefix.

In production every request goes through frontend/nginx.conf, which proxies only the path
prefixes it lists; anything else gets the React app. A router whose prefix is missing there
works in development and fails in production (the Graph page did: 405 on its query).
"""
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from services.auth import create_access_token

ROOT = Path(__file__).resolve().parents[2]
NGINX = ROOT / "frontend" / "nginx.conf"
APP_TSX = ROOT / "frontend" / "src" / "App.tsx"

GUARDED = [
    ("get", "/merge/groups"),
    ("post", "/merge/scan"),
    ("post", "/merge/execute"),
    ("post", "/backfill/topics"),
    ("get", "/claims/search?q=x"),
    ("post", "/author-tracker/check-all"),
]
ADMIN_ONLY = [r for r in GUARDED if r[1].startswith(("/merge", "/backfill"))]


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", GUARDED)
async def test_requires_login(method, path):
    async with _client() as c:
        r = await getattr(c, method)(path)
    assert r.status_code == 401, (path, r.status_code)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", ADMIN_ONLY)
async def test_admin_only_for_non_admins(method, path):
    token = create_access_token({"sub": "someone"})
    with patch("db.connection.get_driver"), patch("db.queries.users.is_user_admin", return_value=False):
        async with _client() as c:
            r = await getattr(c, method)(path, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403, (path, r.status_code)


def test_require_admin_passes_admins():
    from services.auth import require_admin

    with patch("db.connection.get_driver"), patch("db.queries.users.is_user_admin", return_value=True):
        assert require_admin("boss") == "boss"


# ── nginx ────────────────────────────────────────────────────────────────────

# Served by FastAPI itself or not meant for production.
NOT_PROXIED = {"redoc", "ollama", "docs"}


def _api_prefixes() -> set[str]:
    segs = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        seg = path.strip("/").split("/")[0]
        if seg and not seg.startswith("{"):
            segs.add(seg)
    return segs - NOT_PROXIED - {"openapi.json"}


needs_frontend = pytest.mark.skipif(
    not NGINX.exists(), reason="frontend/ is not in this checkout (e.g. inside the backend container)"
)


def _nginx_proxied() -> tuple[set[str], list[re.Pattern]]:
    conf = NGINX.read_text()
    prefixes = {m.strip("/") for m in re.findall(r"^\s*location\s+(/[\w./-]*)\s*\{", conf, re.M)}
    regexes = [re.compile(m) for m in re.findall(r"^\s*location\s+~\s+(\S+)\s*\{", conf, re.M)]
    return prefixes, regexes


def _proxied(seg: str, prefixes, regexes) -> bool:
    """nginx prefix locations match on the start of the path, so /knowledge-chat covers itself."""
    path = f"/{seg}/x"
    return any(path.startswith(f"/{p}") for p in prefixes if p) or any(r.search(path) for r in regexes)


@needs_frontend
def test_every_api_prefix_is_proxied_by_nginx():
    prefixes, regexes = _nginx_proxied()
    missing = sorted(s for s in _api_prefixes() if not _proxied(s, prefixes, regexes))
    assert not missing, f"add these to frontend/nginx.conf: {missing}"


@needs_frontend
def test_app_pages_sharing_an_api_prefix_reload_as_the_app():
    """A reload of /projects/<id>/map must get index.html, not backend JSON."""
    conf = NGINX.read_text()
    spa_map = re.search(r'"~\^GET:/\(([^)]*)\)', conf)
    assert spa_map, "the $spa_page map is missing from nginx.conf"
    spa_listed = set(spa_map.group(1).split("|"))
    pages = {m for m in re.findall(r'<Route path="/([\w-]+)', APP_TSX.read_text())}
    prefixes, regexes = _nginx_proxied()
    clashing = {p for p in pages if _proxied(p, prefixes, regexes)}
    assert clashing, "expected app pages such as /projects to share a prefix with the API"
    assert not clashing - spa_listed, f"add to the $spa_page map: {sorted(clashing - spa_listed)}"
