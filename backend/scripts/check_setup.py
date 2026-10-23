#!/usr/bin/env python3
"""Check a fresh install: settings, database, AI provider and file storage.

Run inside the app container (see DEPLOY.md):
    docker compose -f docker-compose.selfhost.yml exec app python scripts/check_setup.py
Prints no secrets. Exits 1 when something required is missing. --no-ai skips the test call.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings  # noqa: E402

failed = False


def report(ok: bool, label: str, detail: str = "", required: bool = True) -> None:
    global failed
    mark = "ok  " if ok else ("FAIL" if required else "warn")
    failed |= required and not ok
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))


def main() -> None:
    report(bool(settings.jwt_secret_key.strip()), "JWT_SECRET_KEY set", "" if settings.jwt_secret_key.strip() else "run: openssl rand -hex 32")

    try:
        from db.connection import get_driver
        from db.queries.users import get_user_by_name

        driver = get_driver()
        driver.verify_connectivity()
        report(True, "Neo4j reachable", settings.neo4j_uri)
        owner = settings.default_user_name
        exists = bool(get_user_by_name(driver, owner))
        report(exists, f"Owner account '{owner}' exists",
               "" if exists else "run scripts/create_default_user.py yourself (it asks for a password)")
    except Exception as exc:  # noqa: BLE001
        report(False, "Neo4j reachable", f"{type(exc).__name__}: {exc} (it needs ~30 s after the first start)")

    from services.litellm_client import chat_completion, fast_model, fast_provider

    provider = fast_provider()
    report(provider is not None, "AI provider", f"{provider} -> fast model {fast_model()}" if provider
           else "set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env")
    if provider and "--no-ai" not in sys.argv:
        try:
            answer = chat_completion([{"role": "user", "content": "Reply with the single word: ready"}],
                                     max_tokens=20, timeout=60)
            report(bool(answer), "Fast model answers", answer[:40])
        except Exception as exc:  # noqa: BLE001
            report(False, "Fast model answers", f"{type(exc).__name__}: {str(exc)[:200]}")
    report(bool(settings.anthropic_api_key.strip()), "Claude chat (Sonnet/Opus)",
           "available" if settings.anthropic_api_key.strip() else "no ANTHROPIC_API_KEY: chat uses the fast model",
           required=False)

    from services.drive import uses_local_storage

    if uses_local_storage():
        folder = Path(settings.local_storage_dir)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / ".write-test"
            probe.write_bytes(b"ok")
            probe.unlink()
            report(True, "PDF storage", f"local folder {folder}")
        except OSError as exc:
            report(False, "PDF storage", f"local folder {folder} not writable: {exc}")
    else:
        token = Path(settings.google_token_file or Path(__file__).parent.parent / "token.json")
        has_token = token.exists() or bool(settings.google_token_json.strip())
        report(has_token, "PDF storage", "Google Drive" if has_token
               else f"Google Drive selected but {token} is missing (docs/self_hosting.md step 2)")

    report(settings.docling_mode.strip().lower() == "local" or bool(settings.inference_manager_url.strip()),
           "PDF layout model", f"DOCLING_MODE={settings.docling_mode}", required=False)
    print(f"[info] Accent colour: {settings.ui_accent}")
    print("\nAll required checks passed." if not failed else "\nSome required checks failed (see FAIL above).")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
