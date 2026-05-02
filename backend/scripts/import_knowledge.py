"""Import knowledge base entries from a JSON dump into any backend environment.

Reads a JSON array (as produced by `export_knowledge.py`) and POSTs each entry
to `/api/knowledge`. Optionally skip entries whose (title, category) already
exist in the target environment.

Usage:

    # Default: load backend/seed_data/knowledge.json into http://localhost:8001
    python backend/scripts/import_knowledge.py

    # Push to production / staging
    python backend/scripts/import_knowledge.py \\
        --base-url https://api.example.com \\
        --input backend/seed_data/knowledge.json \\
        --username admin --password "$KB_PASSWORD"

    # Re-run safely (skip duplicates by title+category)
    python backend/scripts/import_knowledge.py --skip-existing
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _request(url: str, method: str = "GET", payload: dict | None = None, token: str | None = None) -> dict | list:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {e.code} from {url}: {detail}") from e


def login(base_url: str, username: str, password: str) -> str:
    data = _request(
        f"{base_url}/api/auth/login",
        method="POST",
        payload={"username": username, "password": password},
    )
    if not isinstance(data, dict) or "access_token" not in data:
        raise SystemExit(f"Login response missing access_token: {data}")
    return data["access_token"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("KB_BASE_URL", "http://localhost:8001"))
    parser.add_argument("--username", default=os.environ.get("KB_USERNAME", "admin"))
    parser.add_argument(
        "--password",
        default=os.environ.get("KB_PASSWORD", "change-me-in-production"),
    )
    parser.add_argument(
        "--input",
        default="backend/seed_data/knowledge.json",
        help="Input JSON path (relative to current working dir).",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip entries whose (title, category) already exist on target.",
    )
    args = parser.parse_args()

    in_path = os.path.abspath(args.input)
    if not os.path.isfile(in_path):
        raise SystemExit(f"Input file not found: {in_path}")

    with open(in_path, "r", encoding="utf-8") as f:
        entries = json.load(f)
    if not isinstance(entries, list):
        raise SystemExit(f"Expected JSON array in {in_path}")
    print(f"[import] loaded {len(entries)} entries from {in_path}")

    print(f"[import] logging in to {args.base_url} as {args.username}")
    token = login(args.base_url, args.username, args.password)
    print("[import] login ok")

    existing_keys: set[tuple[str, str]] = set()
    if args.skip_existing:
        existing = _request(f"{args.base_url}/api/knowledge", token=token)
        if isinstance(existing, list):
            existing_keys = {(e.get("title", ""), e.get("category") or "") for e in existing}
            print(f"[import] target already has {len(existing_keys)} entries; skip-existing enabled")

    created = 0
    skipped = 0
    failed = 0
    for idx, entry in enumerate(entries, 1):
        title = entry.get("title") or ""
        category = entry.get("category") or ""
        if args.skip_existing and (title, category) in existing_keys:
            skipped += 1
            continue
        payload = {
            "title": title,
            "content": entry.get("content") or "",
            "source": entry.get("source"),
            "category": entry.get("category"),
        }
        print(f"[import] ({idx}/{len(entries)}) {category or '(uncategorized)'} :: {title}")
        try:
            _request(f"{args.base_url}/api/knowledge", method="POST", payload=payload, token=token)
            created += 1
        except SystemExit as exc:
            failed += 1
            print(f"  ! failed: {exc}", file=sys.stderr)

    print(f"[import] done; created={created} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    main()
