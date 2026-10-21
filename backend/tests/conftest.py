# pythonpath = . in pytest.ini handles path setup

import os

# The endpoint tests drive the app through httpx's ASGI transport with
# base_url="http://test", so the request Host header is "test". The app wraps
# itself in TrustedHostMiddleware (default allowed hosts: localhost,127.0.0.1),
# which would reject that Host with "400 Invalid host header". Allow the test
# host here before main/config is imported. setdefault keeps any real
# environment override (e.g. CI) intact.
os.environ.setdefault("TRUSTED_HOSTS", "localhost,127.0.0.1,test,testserver")


# Many tests create and delete real nodes through get_driver(). Run against anything but a
# local, throwaway Neo4j they leave test papers, notes and projects in a real library (this
# happened when the suite was run inside the production backend container). Refuse unless
# the database is on this machine, or PM_TESTS_ALLOW_DB=1 says it is disposable.
def pytest_configure(config):
    from urllib.parse import urlparse

    from config import settings

    host = urlparse(settings.neo4j_uri).hostname or ""
    if host not in {"", "localhost", "127.0.0.1", "::1"} and os.environ.get("PM_TESTS_ALLOW_DB") != "1":
        import pytest

        pytest.exit(
            f"Refusing to run tests against the Neo4j at '{host}': tests write to the database. "
            "Point NEO4J_URI at a throwaway local Neo4j, or set PM_TESTS_ALLOW_DB=1 if it is disposable.",
            returncode=2,
        )
