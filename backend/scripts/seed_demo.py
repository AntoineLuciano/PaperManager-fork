#!/usr/bin/env python3
"""Load the demo library into a local development database, to try the app with real-looking data.

    cd backend && python scripts/seed_demo.py                  # adds DEFAULT_USER_NAME to the demo projects
    cd backend && python scripts/seed_demo.py --member alice   # or name the login(s) that should see them

The demo library is the one the tests use (tests/fixtures/demo_library.json): ten well-known
papers on transformers, diffusion and flow models and protein structure, with authors, topics,
tags, two projects, notes with @mentions and #topics, citations, claims, a concept map and a
conversation, plus three fictional users (demo_alice, demo_bob, demo_carol) without passwords.

It only adds data (nothing is deleted) and does nothing if the demo projects already exist.
Like the test suite, it refuses a Neo4j that is not on this machine unless --force is given:
never seed a real library.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from config import settings  # noqa: E402

LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--member", action="append", default=None,
                        help="login name to add to the demo projects (repeatable; default: DEFAULT_USER_NAME)")
    parser.add_argument("--force", action="store_true",
                        help="seed even though NEO4J_URI is not a local database")
    args = parser.parse_args()

    host = urlparse(settings.neo4j_uri).hostname or ""
    if host not in LOCAL_HOSTS and not args.force:
        print(f"Refusing to seed the Neo4j at '{host}': it is not on this machine. Point NEO4J_URI at a "
              "local development database, or pass --force if this one is disposable.", file=sys.stderr)
        return 2

    from db.connection import get_driver
    from db.queries.projects import add_project_member
    from db.schema import run_schema_setup
    from tests.demo_data import demo_spec, load_demo_library

    driver = get_driver()
    spec = demo_spec()
    names = [p["name"] for p in spec["projects"]]
    with driver.session() as session:
        existing = session.run("MATCH (p:Project) WHERE p.name IN $names RETURN count(p) AS n", names=names).single()["n"]
    if existing:
        print("The demo library is already loaded (its projects exist); nothing to do.")
        return 0

    run_schema_setup(driver)
    ids = load_demo_library(driver, spec)
    members = args.member or [settings.default_user_name]
    for project_id in ids["projects"].values():
        for user in members:
            add_project_member(driver, project_id, user, role="admin")

    print(f"Loaded {len(ids['papers'])} papers, {len(ids['people'])} people, {len(ids['projects'])} projects, "
          f"{len(ids['notes'])} notes and {len(ids['conversations'])} conversation.")
    print(f"Added {', '.join(members)} to the projects: {', '.join(names)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
